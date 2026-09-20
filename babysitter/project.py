"""Content-addressed, inspectable checkpoints without git reset/stash."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from .state import Store, uid


class UnsafePath(ValueError):
    pass


class Project:
    def __init__(self, root: Path, store: Store, max_bytes: int = 25_000_000):
        self.root = root.resolve()
        self.store = store
        self.max_bytes = max_bytes
        self.directory = self.root / ".babysitter" / "checkpoints"
        self.blobs = self.directory / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True, mode=0o700)
        top = self.git("rev-parse", "--show-toplevel").strip()
        if Path(top).resolve() != self.root:
            raise ValueError("project root must be the git repository root")

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=self.root,
                                capture_output=True, timeout=15, check=True)
        return result.stdout.decode("utf-8", errors="surrogateescape")

    def safe_path(self, name: str, *, managed: bool = False, allow_leaf_symlink: bool = False) -> Path:
        relative = Path(name)
        if not name or relative.is_absolute() or any(x in {"..", ".git", ".babysitter"} for x in relative.parts):
            raise UnsafePath(f"path outside supervised workspace or reserved: {name}")
        if managed and (relative.name in {"babysitter.json", ".gitignore", ".env"} or relative.name.startswith(".env.")):
            raise UnsafePath("runtime configuration, ignore policy and credential files are protected")
        target = self.root / relative
        for component in [*target.parents][:-1]:
            if component == self.root:
                break
            if component.is_symlink():
                raise UnsafePath(f"symlink parent: {name}")
        if target.is_symlink() and not allow_leaf_symlink:
            raise UnsafePath(f"symlink target: {name}")
        if not target.resolve().is_relative_to(self.root) and not (allow_leaf_symlink and target.is_symlink()):
            raise UnsafePath(f"path escapes workspace: {name}")
        if managed:
            ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", name], cwd=self.root, timeout=15).returncode
            if ignored == 0:
                raise UnsafePath("ignored files are outside managed tool/checkpoint scope")
            if ignored not in {0, 1}:
                raise UnsafePath("could not determine ignore policy")
        return target

    def inventory(self, extra_paths=()) -> dict:
        names = set(self.git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")) - {""}
        names.update(extra_paths)
        entries, total = {}, 0
        for name in sorted(names):
            if any(part in {".git", ".babysitter"} for part in Path(name).parts):
                continue
            path = self.safe_path(name, allow_leaf_symlink=True)
            if not path.exists() and not path.is_symlink():
                continue
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                raise UnsafePath(f"submodules/directories are unsupported in runtime snapshots: {name}")
            if not (stat.S_ISLNK(mode) or stat.S_ISREG(mode)):
                raise UnsafePath(f"nonregular file: {name}")
            total += path.lstat().st_size
            if total > self.max_bytes:
                raise UnsafePath(f"checkpoint exceeds {self.max_bytes} bytes; increase explicit limit")
            content = os.readlink(path).encode() if stat.S_ISLNK(mode) else path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            entries[name] = {"sha256": digest, "mode": stat.S_IMODE(mode), "symlink": stat.S_ISLNK(mode)}
            blob = self.blobs / digest
            if not blob.exists():
                self._durable_write(blob, content)
        return entries

    @staticmethod
    def _durable_write(path: Path, content: bytes) -> None:
        temp = path.with_name(path.name + "." + uid() + ".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def fingerprint(entries: dict) -> str:
        return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()

    def snapshot(self, task_id: str, purpose: str) -> str:
        checkpoint_id = uid()
        previous = self.store.task(task_id)["checkpoint_id"]
        entries = self.inventory(self.manifest(previous) if previous else ())
        manifest = self.directory / f"{checkpoint_id}.json"
        self._durable_write(manifest, json.dumps({"id": checkpoint_id, "files": entries}, indent=2).encode())
        self.store.checkpoint(checkpoint_id, task_id, purpose, manifest)
        return checkpoint_id

    def manifest(self, checkpoint_id: str) -> dict:
        if not checkpoint_id.isalnum():
            raise ValueError("invalid checkpoint ID")
        return json.loads((self.directory / f"{checkpoint_id}.json").read_text())["files"]

    def rollback(self, task_id: str, baseline_id: str) -> str:
        # Persist every failed byte before touching the working tree.
        failed_id = self.snapshot(task_id, "failed_changes")
        baseline, current = self.manifest(baseline_id), self.manifest(failed_id)
        changed = [name for name in baseline.keys() | current.keys() if baseline.get(name) != current.get(name)]
        # Preflight all destinations and blobs before modifying any file.
        for name in changed:
            self.safe_path(name, allow_leaf_symlink=True)
            if name in baseline:
                blob = self.blobs / baseline[name]["sha256"]
                if hashlib.sha256(blob.read_bytes()).hexdigest() != baseline[name]["sha256"]:
                    raise UnsafePath("checkpoint blob is corrupt; refusing rollback")
        for name in sorted(changed, key=lambda x: (-len(Path(x).parts), x)):
            path = self.safe_path(name, allow_leaf_symlink=True)
            if path.exists() or path.is_symlink():
                path.unlink()
        for name in sorted(changed):
            if name not in baseline:
                continue
            entry = baseline[name]
            path = self.safe_path(name, allow_leaf_symlink=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            content = (self.blobs / entry["sha256"]).read_bytes()
            if entry["symlink"]:
                path.symlink_to(content.decode())
            else:
                self._durable_write(path, content)
                path.chmod(entry["mode"])
        self.store.event(task_id, "recover", "rollback.completed", {"baseline_id": baseline_id,
                         "failed_changes_id": failed_id, "files": sorted(changed)})
        return failed_id

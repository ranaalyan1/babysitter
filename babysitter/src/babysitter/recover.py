"""Recovery engine (Recover stage): checkpoints, rollback, retry context.

- :func:`create_checkpoint` snapshots the tree before risky changes.
- :func:`restore_checkpoint` puts it back. Every rollback is recorded in
  the event log (``rollback.done``) and is inspectable via
  ``babysitter trace`` — no silent data loss, ever.
- :func:`build_retry_context` turns a classified failure into the
  failure-context block fed back to the model on retry.

Two checkpoint strategies (both real, both tested):

- ``git-commit`` (preferred when the project is a git repo): a scratch
  commit on the current branch; ``ref`` is the SHA. Restore is
  ``reset --hard`` + ``clean -fd`` (Babysitter's own ``.babysitter/``
  dir is excluded so the event log survives the rollback).
- ``file-copy`` (fallback): full tree copy under
  ``.babysitter/checkpoints/<id>/`` with a manifest; ``ref`` is the copy
  path. Restore deletes added files and rewrites changed ones from the
  manifest.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from .schema import (
    CHECKPOINT_ACTIVE,
    CHECKPOINT_COPY,
    CHECKPOINT_GIT,
    CHECKPOINT_RESTORED,
    CHECKPOINT_SUPERSEDED,
    Checkpoint,
    utcnow,
)
from .store import BabysitterStore, new_checkpoint_id

#: Never checkpoint or delete these (caches, VCS metadata, our own state).
IGNORED_NAMES = frozenset(
    {
        ".babysitter",
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        "target",
        ".pytest_cache",
        ".mypy_cache",
    }
)

_CHECKPOINT_BRANCH_PREFIX = "babysitter-checkpoint-"


class CheckpointError(RuntimeError):
    pass


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )


def is_git_repo(project_root: str | Path) -> bool:
    proc = _run_git(Path(project_root), "rev-parse", "--is-inside-work-tree")
    return proc.returncode == 0


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_tree(root: Path):
    for dirpath, dirnames, filenames in __import__("os").walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_NAMES]
        for name in filenames:
            full = Path(dirpath) / name
            yield full.relative_to(root), full


def create_checkpoint(
    store: BabysitterStore,
    task_id: str,
    project_root: str | Path,
    reason: str,
) -> Checkpoint:
    """Snapshot the tree; prefer git-commit, fall back to file-copy."""
    from .schema import KIND_CHECKPOINT_CREATED, STAGE_RECOVER

    root = Path(project_root)
    checkpoint_id = new_checkpoint_id()
    if is_git_repo(root):
        checkpoint = _git_checkpoint(root, task_id, checkpoint_id, reason)
    else:
        checkpoint = _copy_checkpoint(root, task_id, checkpoint_id, reason)
    # Older active checkpoints for this task are superseded.
    current = store.latest_active_checkpoint(task_id)
    store.save_checkpoint(checkpoint)
    if current is not None:
        store.set_checkpoint_status(current.id, CHECKPOINT_SUPERSEDED)
    store.log_event(
        task_id,
        STAGE_RECOVER,
        KIND_CHECKPOINT_CREATED,
        f"checkpoint {checkpoint.id} ({checkpoint.strategy})",
        {
            "checkpoint_id": checkpoint.id,
            "strategy": checkpoint.strategy,
            "ref": checkpoint.ref,
        },
    )
    return checkpoint


def _git_checkpoint(
    root: Path, task_id: str, checkpoint_id: str, reason: str
) -> Checkpoint:
    _run_git(root, "add", "-A")
    msg = f"{_CHECKPOINT_BRANCH_PREFIX}{checkpoint_id} task={task_id} {reason}"
    commit = _run_git(root, "commit", "-qm", msg, "--allow-empty")
    if commit.returncode != 0:
        raise CheckpointError(f"git commit failed: {commit.stderr.strip()}")
    sha = _run_git(root, "rev-parse", "HEAD")
    if sha.returncode != 0:
        raise CheckpointError("git rev-parse HEAD failed after checkpoint commit")
    return Checkpoint(
        id=checkpoint_id,
        task_id=task_id,
        created_at=utcnow(),
        strategy=CHECKPOINT_GIT,
        ref=sha.stdout.strip(),
        status=CHECKPOINT_ACTIVE,
        reason=reason,
    )


def _copy_checkpoint(
    root: Path, task_id: str, checkpoint_id: str, reason: str
) -> Checkpoint:
    dest = root / ".babysitter" / "checkpoints" / checkpoint_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    manifest: dict[str, str] = {}
    for rel, full in _iter_tree(root):
        if ".babysitter" in rel.parts:
            continue
        target = dest / "tree" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(full, target)
        manifest[str(rel)] = _hash_file(full)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return Checkpoint(
        id=checkpoint_id,
        task_id=task_id,
        created_at=utcnow(),
        strategy=CHECKPOINT_COPY,
        ref=str(dest),
        status=CHECKPOINT_ACTIVE,
        reason=reason,
    )


def restore_checkpoint(
    store: BabysitterStore, checkpoint: Checkpoint, project_root: str | Path
) -> None:
    """Restore the tree to a checkpoint and log ``rollback.done``."""
    from .schema import KIND_ROLLBACK_DONE, STAGE_RECOVER

    root = Path(project_root)
    if checkpoint.strategy == CHECKPOINT_GIT:
        reset = _run_git(root, "reset", "--hard", "--quiet", checkpoint.ref)
        if reset.returncode != 0:
            raise CheckpointError(f"git reset failed: {reset.stderr.strip()}")
        # Remove untracked files the agent added, but keep our own state.
        clean = _run_git(root, "clean", "-fd", "-e", ".babysitter")
        if clean.returncode != 0:
            raise CheckpointError(f"git clean failed: {clean.stderr.strip()}")
    elif checkpoint.strategy == CHECKPOINT_COPY:
        _restore_copy(root, Path(checkpoint.ref))
    else:
        raise CheckpointError(f"unknown checkpoint strategy: {checkpoint.strategy}")
    store.set_checkpoint_status(checkpoint.id, CHECKPOINT_RESTORED)
    store.log_event(
        checkpoint.task_id,
        STAGE_RECOVER,
        KIND_ROLLBACK_DONE,
        f"rolled back to checkpoint {checkpoint.id}",
        {
            "checkpoint_id": checkpoint.id,
            "strategy": checkpoint.strategy,
            "ref": checkpoint.ref,
        },
    )


def _restore_copy(root: Path, dest: Path) -> None:
    manifest_file = dest / "manifest.json"
    if not manifest_file.exists():
        raise CheckpointError(f"checkpoint copy is missing its manifest: {dest}")
    manifest: dict[str, str] = json.loads(manifest_file.read_text())
    wanted = set(manifest)
    # Delete files the agent added (anything present but not in manifest).
    for rel, full in _iter_tree(root):
        if str(rel) not in wanted:
            full.unlink()
    # Rewrite everything from the copy (cheap for v0.1 sizes, always correct).
    for rel_str in wanted:
        src = dest / "tree" / rel_str
        target = root / rel_str
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)


# ---------------------------------------------------------------------------
# Retry context: the failure-context block fed back to the model.
# ---------------------------------------------------------------------------

_CLASS_ADVICE = {
    "tool-error": "The tool call itself failed. Check the tool name, arguments, and paths before retrying.",
    "test-fail": "The change broke the test suite. Read the failing output, fix the code (not the tests), and retry.",
    "syntax-fail": "The change has a syntax/type error. Fix the exact error below and retry.",
    "no-progress-loop": "You are repeating the same failing action. STOP and try a fundamentally different approach.",
    "unknown": "Something failed. Read the evidence carefully and retry with a corrected action.",
}


def build_retry_context(
    failure_class: str,
    evidence_tail: str,
    attempt: int,
    max_attempts: int,
    last_action: str = "",
) -> str:
    advice = _CLASS_ADVICE.get(failure_class, _CLASS_ADVICE["unknown"])
    lines = [
        f"Your last action FAILED (classified: {failure_class}; "
        f"attempt {attempt} of {max_attempts}).",
        advice,
    ]
    if last_action:
        lines.append(f"Failed action: {last_action}")
    if evidence_tail:
        lines.append("Failure evidence (truncated):")
        lines.append(evidence_tail[-2000:])
    lines.append(
        "Fix the problem and call the tool again. Do not claim success "
        "until the change is made and verified."
    )
    return "\n".join(lines)

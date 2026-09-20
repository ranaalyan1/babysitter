"""Deterministic verification is the load-bearing wall, not an LLM opinion."""
from __future__ import annotations

import asyncio
import difflib
import os
import signal
import time
import tempfile
from dataclasses import asdict, dataclass

from .config import Config
from .project import Project


@dataclass
class CommandEvidence:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    output_truncated: bool = False


async def run_command(argv: list[str], project: Project, timeout: float, limit: int) -> CommandEvidence:
    # Verification never receives provider credentials from the runtime environment.
    safe_names = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "VIRTUAL_ENV", "PYTHONPATH", "SYSTEMROOT"}
    env = {key: value for key, value in os.environ.items() if key in safe_names}
    env.update({"CI": "1", "GIT_TERMINAL_PROMPT": "0"})
    # Python validates timestamp-based bytecode by whole-second mtime and size.
    # Rapid same-size edits/rollback can otherwise test yesterday's code. -B alone
    # only disables writes, not reads; a fresh prefix also isolates existing caches.
    with tempfile.TemporaryDirectory(prefix="aletheia-verify-") as cache:
        env.update({"PYTHONPYCACHEPREFIX": cache, "PYTHONDONTWRITEBYTECODE": "1"})
        return await _run_command(argv, project, timeout, limit, env)


async def _run_command(argv: list[str], project: Project, timeout: float, limit: int, env: dict[str, str]) -> CommandEvidence:
    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(*argv, cwd=project.root, env=env,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    except (OSError, ValueError) as exc:
        return CommandEvidence(argv, None, "", str(exc), time.monotonic() - started)

    async def drain(stream):
        data = bytearray()
        truncated = False
        while chunk := await stream.read(8192):
            available = max(0, limit - len(data))
            data.extend(chunk[:available])
            truncated |= len(chunk) > available
        return data.decode(errors="replace"), truncated

    def terminate_group():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    readers = [asyncio.create_task(drain(process.stdout)), asyncio.create_task(drain(process.stderr))]
    timed_out = False
    try:
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except asyncio.TimeoutError:
            timed_out = True
        finally:
            # Also kill descendants left behind by a command that has exited.
            terminate_group()
            await process.wait()
        outputs = await asyncio.gather(*readers)
    except BaseException:
        terminate_group()
        await process.wait()
        await asyncio.gather(*readers, return_exceptions=True)
        raise
    return CommandEvidence(argv, process.returncode, outputs[0][0], outputs[1][0],
                           time.monotonic() - started, timed_out, any(x[1] for x in outputs))


class Verifier:
    def __init__(self, project: Project, config: Config):
        self.project, self.config = project, config

    async def verify(self, baseline_id: str) -> dict:
        baseline = self.project.manifest(baseline_id)
        before = self.project.inventory(baseline)
        commands = []
        missing = []
        for name, argv in (("test", self.config.test_command), ("typecheck", self.config.typecheck_command)):
            if not argv:
                missing.append(name)
                continue
            result = await run_command(argv, self.project, self.config.command_timeout, self.config.max_output_bytes)
            commands.append({"name": name, **asdict(result)})
        git_result = await run_command(["git", "--no-pager", "diff", "--no-ext-diff", "--no-textconv", "--check", "HEAD", "--"],
                                      self.project, self.config.command_timeout, self.config.max_output_bytes)
        commands.append({"name": "git-diff", **asdict(git_result)})
        after = self.project.inventory(baseline)
        changed = sorted(name for name in baseline.keys() | after.keys() if baseline.get(name) != after.get(name))
        diff_parts: list[str] = []
        for name in changed:
            def text(entries):
                return (self.project.blobs / entries[name]["sha256"]).read_bytes().decode(errors="replace").splitlines(True) if name in entries else []
            diff_parts.extend(difflib.unified_diff(text(baseline), text(after), fromfile="before/" + name, tofile="after/" + name))
            if name in baseline and name in after and baseline[name]["mode"] != after[name]["mode"]:
                diff_parts.append(f"mode {name}: {baseline[name]['mode']:o} -> {after[name]['mode']:o}\n")
        diff = "".join(diff_parts)
        failed = [command for command in commands if command["exit_code"] != 0 or command["timed_out"]]
        status, reason = "passed", None
        if before != after:
            status, reason = "failed", "project changed while verification ran; evidence is stale"
        elif failed:
            status, reason = "failed", "one or more verification commands failed"
        elif missing:
            status, reason = "unavailable", "missing configured commands: " + ", ".join(missing)
        limit = self.config.max_output_bytes
        return {"status": status, "reason": reason, "commands": commands, "files": changed,
                "diff": diff[:limit], "diff_truncated": len(diff) > limit,
                "base_fingerprint": self.project.fingerprint(baseline),
                "fingerprint": self.project.fingerprint(after)}

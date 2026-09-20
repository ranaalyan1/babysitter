"""Verification engine (Verify stage): deterministic evidence, not opinion.

Runs the project's real test + typecheck commands as subprocesses and
inspects the real git diff. Returns a verdict:

- ``pass`` — every configured check exited 0.
- ``fail`` — at least one check failed or timed out (evidence attached).
- ``unavailable`` — verification could not run (no commands configured,
  command binary missing, ...). Surfaced, never hidden: callers must not
  treat this as success.

No LLM is consulted anywhere in this module.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_UNAVAILABLE = "unavailable"

#: Keep only the tail of command output; full logs would blow the 16 KiB
#: event-payload budget.
TAIL_CHARS = 4000
DEFAULT_TIMEOUT_S = 180


@dataclass
class CommandResult:
    command: list[str]
    exit_code: int | None  # None when the process never spawned / timed out
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    spawn_error: str = ""


@dataclass
class CheckResult:
    name: str  # "typecheck" | "test"
    passed: bool
    command: list[str]
    exit_code: int | None
    duration_ms: int
    tail: str = ""


@dataclass
class GitDiff:
    available: bool
    clean: bool = True
    files_changed: list[dict] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    reason: str = ""


@dataclass
class VerificationReport:
    verdict: str  # pass | fail | unavailable
    checks: list[CheckResult] = field(default_factory=list)
    git: GitDiff = field(default_factory=lambda: GitDiff(available=False))
    failed_check: str = ""
    tail: str = ""
    unavailable_reason: str = ""

    def to_payload(self) -> dict:
        """Shape matching docs/SCHEMA.md verification.* payloads."""
        base: dict = {
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "command": c.command,
                    "exit_code": c.exit_code,
                    "duration_ms": c.duration_ms,
                }
                for c in self.checks
            ],
            "files_changed": self.git.files_changed,
            "insertions": self.git.insertions,
            "deletions": self.git.deletions,
        }
        if self.verdict == VERDICT_FAIL:
            base["failed_check"] = self.failed_check
            base["tail"] = self.tail
        if self.verdict == VERDICT_UNAVAILABLE:
            return {"reason": self.unavailable_reason}
        return base


def _tail(text: str, limit: int = TAIL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return "…[truncated]…\n" + text[-limit:]


def run_command(
    command: list[str], cwd: str | Path, timeout_s: int = DEFAULT_TIMEOUT_S
) -> CommandResult:
    """Run one command, capturing output. Never raises for command failure;
    only catastrophic local errors (missing binary) are reported in-band."""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return CommandResult(
            command=command,
            exit_code=None,
            duration_ms=int((time.monotonic() - start) * 1000),
            spawn_error=f"command not found: {command[0]}",
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return CommandResult(
            command=command,
            exit_code=None,
            stdout_tail=_tail(out),
            stderr_tail=_tail(err),
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=True,
        )
    duration_ms = int((time.monotonic() - start) * 1000)
    return CommandResult(
        command=command,
        exit_code=proc.returncode,
        stdout_tail=_tail(proc.stdout or ""),
        stderr_tail=_tail(proc.stderr or ""),
        duration_ms=duration_ms,
    )


def _git(repo: str | Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
    )


def git_diff_summary(repo_root: str | Path) -> GitDiff:
    """Inspect the working tree vs HEAD: changed files + line counts."""
    root = Path(repo_root)
    rev = _git(root, "rev-parse", "--is-inside-work-tree")
    if rev.returncode != 0:
        return GitDiff(available=False, reason="not a git repository")

    status = _git(root, "status", "--porcelain=v1", "-uall")
    if status.returncode != 0:
        return GitDiff(
            available=False, reason=f"git status failed: {status.stderr.strip()}"
        )
    entries: list[tuple[str, str]] = []  # (xy, path)
    for line in status.stdout.splitlines():
        if not line.strip():
            continue
        xy, path = line[:2], line[3:].strip()
        if " -> " in path:  # rename: "orig -> new"
            path = path.split(" -> ", 1)[1]
        entries.append((xy, path.strip('"')))
    if not entries:
        return GitDiff(available=True, clean=True)

    numstat = _git(root, "diff", "--numstat", "HEAD", "--", ".")
    counts: dict[str, tuple[int, int]] = {}
    if numstat.returncode == 0:
        for line in numstat.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            try:
                counts[path] = (int(added), int(deleted))
            except ValueError:
                counts[path] = (0, 0)  # binary file: "- -"

    files_changed: list[dict] = []
    insertions = deletions = 0
    for xy, path in entries:
        if xy.strip() == "??" or path not in counts:
            # Untracked (or unborn HEAD): count added lines from the file.
            added = _count_lines(root / path)
            deleted = 0
        else:
            added, deleted = counts[path]
        files_changed.append({"path": path, "added": added, "deleted": deleted})
        insertions += added
        deletions += deleted
    files_changed.sort(key=lambda f: f["path"])
    return GitDiff(
        available=True,
        clean=False,
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
    )


def _count_lines(path: Path) -> int:
    try:
        if path.stat().st_size > 1_000_000:
            return 0
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


class VerificationEngine:
    """Runs configured checks + git inspection for a project.

    config shape (from babysitter.yaml ``verify:`` block)::

        {"test": ["npm", "test"], "typecheck": ["npm", "run", "typecheck"],
         "timeout_s": 180}

    Either command may be null/absent to skip that check. Typecheck runs
    first (fast syntax signal), then tests.
    """

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self.test_cmd: list[str] | None = config.get("test")
        self.typecheck_cmd: list[str] | None = config.get("typecheck")
        self.timeout_s: int = int(config.get("timeout_s", DEFAULT_TIMEOUT_S))

    @property
    def configured(self) -> bool:
        return bool(self.test_cmd or self.typecheck_cmd)

    def run(self, project_root: str | Path) -> VerificationReport:
        root = Path(project_root)
        git = git_diff_summary(root)
        if not self.configured:
            return VerificationReport(
                verdict=VERDICT_UNAVAILABLE,
                git=git,
                unavailable_reason="no verify commands configured"
                " (set verify.test / verify.typecheck)",
            )
        checks: list[CheckResult] = []
        ordered: list[tuple[str, list[str] | None]] = []
        if self.typecheck_cmd:
            ordered.append(("typecheck", self.typecheck_cmd))
        if self.test_cmd:
            ordered.append(("test", self.test_cmd))
        for name, cmd in ordered:
            assert cmd  # configured check above
            result = run_command(cmd, cwd=root, timeout_s=self.timeout_s)
            if result.spawn_error:
                return VerificationReport(
                    verdict=VERDICT_UNAVAILABLE,
                    checks=checks,
                    git=git,
                    unavailable_reason=f"{name}: {result.spawn_error}",
                )
            passed = result.exit_code == 0 and not result.timed_out
            tail = result.stderr_tail or result.stdout_tail
            if result.timed_out:
                tail = f"timed out after {self.timeout_s}s\n" + tail
            checks.append(
                CheckResult(
                    name=name,
                    passed=passed,
                    command=list(cmd),
                    exit_code=result.exit_code,
                    duration_ms=result.duration_ms,
                    tail=tail,
                )
            )
            if not passed:
                return VerificationReport(
                    verdict=VERDICT_FAIL,
                    checks=checks,
                    git=git,
                    failed_check=name,
                    tail=_tail(tail),
                )
        return VerificationReport(verdict=VERDICT_PASS, checks=checks, git=git)

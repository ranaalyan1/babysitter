"""Reversible, project-local installation of Claude Code command hooks."""
from __future__ import annotations

import copy
import json
import math
import shlex
import shutil
import sys
import subprocess
from pathlib import Path

from ..config import Config
from ..project import Project
from ..state import uid

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "SessionEnd")
MARKER = "# babysitter:claude-hooks:v1"


def settings_path(root: Path) -> Path:
    path = root / ".claude" / "settings.local.json"
    for candidate in (root / ".babysitter", path.parent, path):
        if candidate.is_symlink():
            raise ValueError(f"Refusing symlinked integration path: {candidate}")
    return path


def read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("hooks", {}), dict):
        raise ValueError(f"{path} must contain an object with an optional hooks object")
    for groups in value.get("hooks", {}).values():
        if not isinstance(groups, list) or any(not isinstance(group, dict) or not isinstance(group.get("hooks"), list)
                                             or any(not isinstance(hook, dict) for hook in group["hooks"]) for group in groups):
            raise ValueError(f"Invalid hook settings in {path}; existing settings were not changed")
    return value


def owned(hook: dict, marker: str = MARKER) -> bool:
    return hook.get("type") == "command" and isinstance(hook.get("command"), str) and hook["command"].endswith(marker)


def strip_owned(settings: dict, marker: str = MARKER) -> dict:
    result = copy.deepcopy(settings)
    for event, groups in list(result.get("hooks", {}).items()):
        keep = []
        for group in groups:
            hooks = [hook for hook in group["hooks"] if not owned(hook, marker)]
            # Preserve empty/unrelated user groups; remove only our own empty groups.
            if hooks or not any(owned(hook, marker) for hook in group["hooks"]):
                keep.append({**group, "hooks": hooks})
        if keep:
            result["hooks"][event] = keep
        elif groups:
            result["hooks"].pop(event)
    if "hooks" in result and not result["hooks"]:
        result.pop("hooks")
    return result


def hook_timeout(config: Config) -> int:
    # test + typecheck + git command timeouts, inventory, rollback, and cleanup.
    return math.ceil(3 * config.command_timeout + 90)


def command(root: Path, event: str) -> str:
    # Do NOT resolve a virtualenv interpreter symlink to the system Python.
    argv = [str(Path(sys.executable).absolute()), "-m", "babysitter.adapters.claude", "--root", str(root), "--event", event]
    return (shlex.join(argv) + "; status=$?; if [ \"$status\" -ne 0 ]; then "
            "printf '%s\\n' 'Babysitter hook failed. Task is NOT VERIFIED. Inspect installation and trace.' >&2; exit 2; fi; " + MARKER)


def _save(root: Path, path: Path, before: dict, after: dict) -> str | None:
    if before == after:
        return None
    backups = root / ".babysitter" / "install-backups"
    if backups.is_symlink():
        raise ValueError("Refusing symlinked backup directory")
    (root / ".babysitter").mkdir(exist_ok=True, mode=0o700)
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backups / f"{uid()}.{path.name}"
    Project._durable_write(backup, path.read_bytes() if path.exists() else b"{}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    Project._durable_write(path, (json.dumps(after, indent=2) + "\n").encode())
    path.chmod(mode)
    return str(backup)


def install(root: Path) -> dict:
    root = root.resolve()
    path = settings_path(root)
    if not (root / "babysitter.json").is_file():
        raise ValueError("Run babysitter init with --test and --typecheck before installing the adapter")
    config = Config.load(root)
    try:
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root, stderr=subprocess.PIPE, text=True, timeout=10).strip()
        subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, capture_output=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Claude hooks require a git repository with at least one commit") from exc
    if Path(top).resolve() != root:
        raise ValueError("Install Claude hooks at the git repository root, not a subdirectory")
    if not config.test_command or not config.typecheck_command:
        raise ValueError("Both test_command and typecheck_command are required before installing Claude hooks")
    before = read_settings(path)
    project_settings = read_settings(root / ".claude" / "settings.json")
    if before.get("disableAllHooks") or project_settings.get("disableAllHooks"):
        raise ValueError("Claude settings have disableAllHooks enabled; enable hooks explicitly before installing")
    after = strip_owned(before)
    hooks = after.setdefault("hooks", {})
    for event in EVENTS:
        entry = {"type": "command", "command": command(root, event),
                 "timeout": hook_timeout(config) if event == "Stop" else (10 if event == "SessionEnd" else 60)}
        group: dict = {"hooks": [entry]}
        if event in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
            group["matcher"] = ".*"
        hooks.setdefault(event, []).append(group)
    backup = _save(root, path, before, after)
    return {"installed": True, "changed": before != after, "settings": str(path), "backup": backup,
            "events": list(EVENTS), "claude_executable": shutil.which("claude"),
            "next": "Start a fresh Claude Code session in this repository and check /hooks. No Babysitter server or provider is required."}


def uninstall(root: Path) -> dict:
    root = root.resolve()
    path = settings_path(root)
    before = read_settings(path)
    after = strip_owned(before)
    backup = _save(root, path, before, after)
    return {"installed": False, "changed": before != after, "settings": str(path), "backup": backup,
            "retained": "All unrelated Claude settings and all Babysitter evidence/checkpoints"}


def status(root: Path) -> dict:
    root = root.resolve()
    settings = read_settings(settings_path(root))
    config = Config.load(root)
    problems = []
    if not (root / "babysitter.json").is_file():
        problems.append("Missing babysitter.json; run babysitter init")
    if not config.test_command or not config.typecheck_command:
        problems.append("Both verification commands must be configured")
    installed = []
    for event in EVENTS:
        matches = [hook for group in settings.get("hooks", {}).get(event, []) for hook in group["hooks"] if owned(hook)]
        if len(matches) != 1 or matches[0]["command"] != command(root, event):
            problems.append(f"{event}: missing, duplicated, or stale hook; reinstall from the current environment")
        elif event == "Stop" and (not isinstance(matches[0].get("timeout"), (int, float)) or matches[0]["timeout"] < hook_timeout(config)):
            problems.append("Stop hook timeout is shorter than the current verification budget; reinstall")
        else:
            installed.append(event)
    project_settings = read_settings(root / ".claude" / "settings.json")
    if settings.get("disableAllHooks") or project_settings.get("disableAllHooks"):
        problems.append("Hooks are disabled in project/local Claude settings")
    executable = shutil.which("claude")
    return {"ok": not problems, "installed_events": installed, "problems": problems, "claude_executable": executable,
            "status_scope": "local configuration inspection, not an authenticated model test", "visibility": "native hook callbacks + independent project verification",
            "warnings": (["Claude Code executable is not on PATH; install it through its official distribution"] if not executable else []) +
                        ["Use /hooks to confirm effective settings; global/managed settings may override project hooks",
                         "Single main-thread, foreground work in a dedicated worktree only",
                         "Model switching belongs to Claude Code; this adapter does not call the proxy provider"]}

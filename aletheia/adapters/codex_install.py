"""Project-local Codex hook configuration; never grant hook trust or permissions."""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from ..config import Config
from .claude_install import _save, hook_timeout, owned, read_settings, strip_owned

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd", "Interrupt")
MARKER = "# aletheia:codex-hooks:v1"


def settings_path(root: Path) -> Path:
    path = root / ".codex" / "hooks.json"
    for candidate in (root / ".aletheia", path.parent, path, root / ".codex" / "config.toml"):
        if candidate.is_symlink():
            raise ValueError(f"Refusing symlinked integration path: {candidate}")
    return path


def disabled(root: Path) -> bool:
    path = root / ".codex" / "config.toml"
    config = tomllib.loads(path.read_text()) if path.exists() else {}
    features = config.get("features", {})
    if not isinstance(features, dict):
        raise ValueError("Codex project features config must be a TOML table")
    return features.get("hooks", features.get("codex_hooks", True)) is False


def command(root: Path, event: str) -> str:
    argv = [str(Path(sys.executable).absolute()), "-m", "aletheia.adapters.codex", "--root", str(root), "--event", event]
    return (shlex.join(argv) + "; status=$?; if [ \"$status\" -ne 0 ]; then "
            "printf '%s\\n' 'Aletheia hook failed. Task is NOT VERIFIED. Inspect installation and trace.' >&2; exit 2; fi; " + MARKER)


def install(root: Path) -> dict:
    root = root.resolve()
    path = settings_path(root)
    if not (root / "aletheia.json").is_file():
        raise ValueError("Run aletheia init with --test and --typecheck before installing Codex hooks")
    config = Config.load(root)
    if not config.test_command or not config.typecheck_command:
        raise ValueError("Both test_command and typecheck_command are required")
    try:
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root, stderr=subprocess.PIPE, text=True, timeout=10).strip()
        subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Codex hooks require a git repository with at least one commit") from exc
    if Path(top).resolve() != root:
        raise ValueError("Install at the git repository root")
    if disabled(root):
        raise ValueError("Codex hooks are explicitly disabled in project config; enable them yourself before installing")
    before = read_settings(path)
    after = strip_owned(before, MARKER)
    hooks = after.setdefault("hooks", {})
    for event in EVENTS:
        handler = {"type": "command", "command": command(root, event),
                   "timeout": hook_timeout(config) if event == "Stop" else 3 if event in {"SessionEnd", "Interrupt"} else 60}
        group: dict = {"hooks": [handler]}
        if event in {"PreToolUse", "PostToolUse"}:
            group["matcher"] = ".*"
        hooks.setdefault(event, []).append(group)
    backup = _save(root, path, before, after)
    return {"installed": True, "changed": before != after, "settings": str(path), "backup": backup, "events": list(EVENTS),
            "trust_granted": False, "next": "In Codex, trust this project and review/trust these exact hook definitions with /hooks. Start a fresh session. Permissions/sandbox remain unchanged."}


def uninstall(root: Path) -> dict:
    root = root.resolve()
    path = settings_path(root)
    before = read_settings(path)
    after = strip_owned(before, MARKER)
    return {"installed": False, "changed": before != after, "backup": _save(root, path, before, after),
            "retained": "Unrelated hooks, Codex config/trust/credentials, and all Aletheia evidence"}


def status(root: Path) -> dict:
    root = root.resolve()
    settings = read_settings(settings_path(root))
    config = Config.load(root)
    problems = []
    if not (root / "aletheia.json").is_file() or not config.test_command or not config.typecheck_command:
        problems.append("Initialize both verification commands first")
    if disabled(root):
        problems.append("Project config has hooks disabled")
    for event in EVENTS:
        matches = [(group, h) for group in settings.get("hooks", {}).get(event, []) for h in group["hooks"] if owned(h, MARKER)]
        if len(matches) != 1:
            problems.append(f"{event}: missing or duplicate hook; reinstall")
            continue
        group, handler = matches[0]
        if handler["command"] != command(root, event) or handler.get("async") or group.get("matcher") != (".*" if event in {"PreToolUse", "PostToolUse"} else None):
            problems.append(f"{event}: stale, asynchronous or incorrectly matched hook; reinstall")
        expected_timeout = hook_timeout(config) if event == "Stop" else 3 if event in {"Interrupt", "SessionEnd"} else 60
        actual_timeout = handler.get("timeout")
        if isinstance(actual_timeout, bool) or not isinstance(actual_timeout, (int, float)) or actual_timeout < expected_timeout:
            problems.append(f"{event}: hook timeout needs reinstall for current command budget")
    return {"ok": not problems, "problems": problems, "codex_executable": shutil.which("codex"), "hook_trust": "not inspected or granted",
            "warnings": ["Review/trust project + hooks in Codex /hooks; untrusted/disabled hooks do not run",
                         "Single main-thread foreground work; native permissions/sandbox remain authoritative",
                         "Hosted/specialized tools may bypass hook coverage; model selection belongs to Codex"]}

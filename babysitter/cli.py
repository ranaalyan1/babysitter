from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config
from .metrics import metrics
from .provider import OpenAIProvider, ProviderError
from .state import Store


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="babysitter", description="AI coding agents may claim success. Babysitter requires evidence.")
    cli.add_argument("--root", type=Path, default=Path.cwd(), help="git repository root (default: current directory)")
    commands = cli.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="write local runtime configuration")
    init.add_argument("--provider-url", default=Config.provider_url)
    init.add_argument("--model", default=Config.model)
    init.add_argument("--stronger-model")
    init.add_argument("--test", default="", help="test command; parsed into argv, never executed through a shell")
    init.add_argument("--typecheck", default="", help="typecheck command; parsed into argv")
    init.add_argument("--managed-tools", action="store_true", help="opt into read_file/write_file execution")
    start = commands.add_parser("start", help="start protocol supervision server")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=8030)
    doctor = commands.add_parser("doctor", help="check project, configuration, commands and provider")
    doctor.add_argument("--offline", action="store_true", help="skip provider connectivity probe")
    trace = commands.add_parser("trace", help="inspect persisted task events/evidence/checkpoints")
    trace.add_argument("task_id", nargs="?")
    trace.add_argument("--metrics", action="store_true")
    trace.add_argument("--checkpoint", help="inspect the manifest and file contents of a retained checkpoint")
    claude = commands.add_parser("claude", help="install, inspect, or remove the opt-in native Claude Code hooks")
    claude.add_argument("action", choices=["install", "status", "uninstall"])
    codex = commands.add_parser("codex", help="install, inspect, or remove native Codex hooks")
    codex.add_argument("action", choices=["install", "status", "uninstall"])
    opencode = commands.add_parser("opencode", help="supervise an owned OpenCode CLI run")
    actions = opencode.add_subparsers(dest="action", required=True)
    op_run = actions.add_parser("run", help="run, independently verify, and recover the same native session")
    op_run.add_argument("prompt")
    op_run.add_argument("--executable", default="opencode")
    op_run.add_argument("--model", help="native provider/model selection; no Babysitter provider routing")
    op_run.add_argument("--timeout", type=float, default=600, help="maximum seconds per native agent invocation")
    op_status = actions.add_parser("status", help="check wrapper prerequisites")
    op_status.add_argument("--executable", default="opencode")
    ui = commands.add_parser("ui", help="open the read-only local supervision console")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8040)
    ui.add_argument("--demo", action="store_true", help="use labeled synthetic data; never read repository state")
    return cli


async def doctor(root: Path, config: Config, offline: bool) -> dict:
    checks = []
    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    check("configuration", (root / "babysitter.json").is_file(), "babysitter.json")
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True, timeout=10)
        check("git-root", result.returncode == 0 and Path(result.stdout.strip()).resolve() == root, result.stdout.strip() or result.stderr.strip())
        head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        check("git-baseline", head.returncode == 0, "git diff inspection requires at least one commit")
    except (OSError, subprocess.TimeoutExpired) as exc:
        check("git-root", False, str(exc))
    for name, command in (("test", config.test_command), ("typecheck", config.typecheck_command)):
        executable = shutil.which(command[0]) if command else None
        if command and "/" in command[0]:
            path = root / command[0]
            executable = str(path) if path.is_file() and os.access(path, os.X_OK) else None
        check(name, bool(command and executable), {"argv": command, "executable": executable})
    check("managed-tools", True, "enabled (read_file/write_file only)" if config.allow_managed_tools else "disabled; relay mode only")
    check("visibility", True, "protocol + independent verification; no IDE internals")
    if not offline:
        provider = OpenAIProvider(config)
        try:
            models = await provider.models()
            ids = [item.get("id") for item in models["data"]]
            check("provider", True, {"models": ids})
            check("base-model", config.model in ids, config.model)
            if config.stronger_model:
                check("stronger-model", config.stronger_model in ids, config.stronger_model)
        except ProviderError as exc:
            check("provider", False, str(exc))
        finally:
            await provider.close()
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "init":
            if (root / "babysitter.json").exists():
                raise ValueError("babysitter.json already exists; edit it explicitly (init will not overwrite)")
            config = Config(provider_url=args.provider_url, model=args.model, stronger_model=args.stronger_model,
                            test_command=shlex.split(args.test), typecheck_command=shlex.split(args.typecheck), allow_managed_tools=args.managed_tools)
            config.save(root)
            ignore = root / ".gitignore"
            content = ignore.read_text() if ignore.exists() else ""
            for pattern in (".babysitter/", ".env"):
                if pattern not in content.splitlines():
                    content = content.rstrip("\n") + "\n" + pattern + "\n"
            ignore.write_text(content)
            print("Created babysitter.json. Provider keys are read only from BABYSITTER_PROVIDER_API_KEY.")
            if not config.test_command or not config.typecheck_command:
                print("WARNING: missing test/typecheck commands; completion will be verification_unavailable.")
        elif args.command == "claude":
            from .adapters import claude_install
            report = getattr(claude_install, args.action)(root)
            print(json.dumps(report, indent=2))
            return 0 if report.get("ok", True) else 1
        elif args.command == "codex":
            from .adapters import codex_install
            report = getattr(codex_install, args.action)(root)
            print(json.dumps(report, indent=2))
            return 0 if report.get("ok", True) else 1
        elif args.command == "opencode":
            from .adapters import opencode
            report = opencode.run(root, args.prompt, args.executable, args.model, args.timeout) if args.action == "run" else opencode.status(root, args.executable)
            print(json.dumps(report, indent=2))
            return 0 if report.get("verified", report.get("ok", False)) else 1
        elif args.command == "trace":
            if not (root / ".babysitter" / "state.sqlite3").exists():
                raise ValueError("No runtime state exists in this repository")
            store = Store(root / ".babysitter")
            try:
                result = store.trace(args.task_id)
                if args.task_id and not result["tasks"]:
                    raise ValueError("Unknown task")
                if args.checkpoint:
                    checkpoint = next((c for c in result["checkpoints"] if c["id"] == args.checkpoint), None)
                    if not checkpoint:
                        raise ValueError("Checkpoint not found in selected trace")
                    manifest = json.loads(Path(checkpoint["manifest_path"]).read_text())
                    for entry in manifest["files"].values():
                        blob = Path(checkpoint["manifest_path"]).parent / "blobs" / entry["sha256"]
                        content = blob.read_bytes()
                        entry["content_preview"] = content[:64000].decode(errors="replace")
                        entry["preview_truncated"] = len(content) > 64000
                    result = {"checkpoint": checkpoint, "manifest": manifest}
                elif args.metrics:
                    result = metrics(result)
                print(json.dumps(result, indent=2, ensure_ascii=True))
            finally:
                store.close()
        elif args.command == "doctor":
            report = asyncio.run(doctor(root, Config.load(root), args.offline))
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1
        elif args.command == "ui":
            if not args.demo and args.host not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get("BABYSITTER_UI_TOKEN"):
                raise ValueError("Non-loopback real console access requires BABYSITTER_UI_TOKEN; use --demo for a safe public preview")
            import uvicorn
            from .console import create_console
            uvicorn.run(create_console(root, demo=args.demo), host=args.host, port=args.port)
        elif args.command == "start":
            config = Config.load(root)
            if args.host not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get(config.token_env):
                raise ValueError(f"Binding a non-loopback address requires {config.token_env}; never expose workspace tools unauthenticated")
            import uvicorn
            from .server import create_app
            uvicorn.run(create_app(root, config), host=args.host, port=args.port, workers=1)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"babysitter: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

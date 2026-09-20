"""Babysitter CLI: init / start / doctor / trace / demo.

- ``init`` — scaffold babysitter.json + state dir in a project.
- ``start`` — run the protocol server (Layer 1).
- ``doctor`` — check that supervision can actually work here.
- ``trace`` — inspect tasks and their event logs / metrics.
- ``demo`` — the v0.1 acceptance demo, end to end, no human in the loop.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG_NAME = "babysitter.json"
STATE_DIR = ".babysitter"
DB_NAME = "babysitter.db"

DEFAULT_CONFIG = {
    "verify": {"test": None, "typecheck": None, "timeout_s": 180},
    "provider": {
        "base_url": "http://localhost:11434/v1",
        "api_key_env": "BABYSITTER_API_KEY",
        "comment": "One OpenAI-compatible endpoint (e.g. Ollama). "
        "All ladder models live on it.",
    },
    "ladder": ["weak-model"],
    "escalation_threshold": 2,
    "max_steps": 12,
    "max_attempts_per_step": 3,
}


def project_paths(project_root: str | Path) -> tuple[Path, Path, Path]:
    root = Path(project_root).resolve()
    return root, root / CONFIG_NAME, root / STATE_DIR / DB_NAME


def load_config(project_root: str | Path) -> dict:
    root, cfg_path, _ = project_paths(project_root)
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if cfg_path.exists():
        loaded = json.loads(cfg_path.read_text())
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    config["_project_root"] = str(root)
    return config


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def detect_verify_commands(root: Path) -> dict:
    """Best-effort detection of test/typecheck commands. Returns argv lists
    (or None) for the config template."""
    test: list[str] | None = None
    typecheck: list[str] | None = None
    package_json = root / "package.json"
    if package_json.exists():
        try:
            scripts = json.loads(package_json.read_text()).get("scripts", {})
        except ValueError:
            scripts = {}
        if "test" in scripts:
            test = ["npm", "test", "--silent"]
        for name in ("typecheck", "lint", "check"):
            if name in scripts:
                typecheck = ["npm", "run", name, "--silent"]
                break
    if test is None and (
        (root / "pytest.ini").exists()
        or (root / "pyproject.toml").exists()
        or (root / "setup.py").exists()
        or (root / "setup.cfg").exists()
    ):
        test = [sys.executable, "-m", "pytest", "-q"]
    return {"test": test, "typecheck": typecheck, "timeout_s": 180}


def cmd_init(args: argparse.Namespace) -> int:
    from .store import BabysitterStore

    root, cfg_path, db_path = project_paths(args.project_root)
    if not root.exists():
        print(f"error: project root does not exist: {root}", file=sys.stderr)
        return 1
    verify = detect_verify_commands(root)
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["verify"] = verify
    if cfg_path.exists() and not args.force:
        print(f"{cfg_path} already exists (use --force to overwrite)")
    else:
        cfg_path.write_text(json.dumps(config, indent=2) + "\n")
        print(f"wrote {cfg_path}")
    store = BabysitterStore(db_path)
    store.close()
    print(f"state dir: {root / STATE_DIR}")
    if verify["test"] is None:
        print("warning: no test command detected; set verify.test in "
              f"{CONFIG_NAME} or verification will be unavailable.")
    else:
        print(f"detected test command: {' '.join(verify['test'])}")
    if verify["typecheck"]:
        print(f"detected typecheck command: {' '.join(verify['typecheck'])}")
    print("next: babysitter doctor && babysitter start")
    return 0


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def build_providers(config: dict):
    from .provider import OpenAICompatProvider

    provider_cfg = config.get("provider", {})
    base_url = provider_cfg.get("base_url", "http://localhost:11434/v1")
    api_key = os.environ.get(provider_cfg.get("api_key_env", ""), "")
    providers = {}
    for model_id in config.get("ladder", ["weak-model"]):
        providers[model_id] = OpenAICompatProvider(model_id, base_url, api_key)
    return providers


def cmd_start(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import ServerConfig, create_app

    config = load_config(args.project_root)
    server_config = ServerConfig(
        project_root=config["_project_root"],
        db_path=str(Path(config["_project_root"]) / STATE_DIR / DB_NAME),
        providers=build_providers(config),
        ladder=config.get("ladder", ["weak-model"]),
        verify=config.get("verify", {}),
        escalation_threshold=int(config.get("escalation_threshold", 2)),
    )
    app = create_app(server_config)
    print(f"babysitter supervising {server_config.project_root}")
    print(f"ladder: {' -> '.join(server_config.ladder)}")
    print(f"listening on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    from .store import BabysitterStore

    root, cfg_path, db_path = project_paths(args.project_root)
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        mark = "ok  " if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures += 1

    check("project root exists", root.exists(), str(root))
    if cfg_path.exists():
        try:
            config = load_config(root)
            check("config parses", True, str(cfg_path))
        except ValueError as exc:
            check("config parses", False, str(exc))
            config = json.loads(json.dumps(DEFAULT_CONFIG))
    else:
        check("config exists", False, f"run: babysitter init --project-root {root}")
        config = json.loads(json.dumps(DEFAULT_CONFIG))

    try:
        store = BabysitterStore(db_path)
        store.close()
        check("state db writable", True, str(db_path))
    except Exception as exc:  # noqa: BLE001 - doctor reports, never crashes
        check("state db writable", False, str(exc))

    git = shutil.which("git")
    check("git available", git is not None)
    if git:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
        )
        check("project is a git repo", proc.returncode == 0,
              "" if proc.returncode == 0 else "git diff unavailable; "
              "checkpoints will use file-copy")

    verify = config.get("verify", {})
    for name in ("test", "typecheck"):
        cmd = verify.get(name)
        if not cmd:
            check(f"verify.{name} configured", name == "typecheck",
                  "not configured" if name == "test"
                  else "not configured (optional)")
            continue
        binary = shutil.which(cmd[0])
        check(f"verify.{name} binary exists", binary is not None,
              " ".join(cmd))

    providers = build_providers(config)
    ladder = config.get("ladder", [])
    if ladder:
        status = providers[ladder[0]].check()
        check(f"provider reachable ({ladder[0]})", status == "ok", status)
    if len(ladder) > 1:
        check("escalation ladder", True, " -> ".join(ladder))
    else:
        check("escalation ladder", True, "single model; "
              "escalation will report no-stronger-model")

    print("doctor: " + ("all checks passed" if failures == 0
                        else f"{failures} check(s) FAILED"))
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------


def cmd_trace(args: argparse.Namespace) -> int:
    from .metrics import global_metrics, task_metrics
    from .store import BabysitterStore

    _, _, db_path = project_paths(args.project_root)
    if not db_path.exists():
        print(f"no state db at {db_path}; run babysitter init first",
              file=sys.stderr)
        return 1
    store = BabysitterStore(db_path)
    try:
        if args.metrics and not args.task_id:
            print(json.dumps(global_metrics(store), indent=2))
            return 0
        if not args.task_id:
            tasks = store.list_tasks(limit=args.limit)
            if not tasks:
                print("no tasks yet")
                return 0
            for task in tasks:
                print(f"{task.id}  [{task.status}]  {task.goal[:70]}")
            return 0
        task = store.get_task(args.task_id)
        if task is None:
            print(f"unknown task: {args.task_id}", file=sys.stderr)
            return 1
        print(f"task {task.id} [{task.status}] model={task.model}")
        print(f"goal: {task.goal}")
        if args.metrics:
            print(json.dumps(task_metrics(store, task.id), indent=2))
            return 0
        events = store.list_events(
            task.id,
            kinds=args.kind,
            stages=args.stage,
            limit=args.limit,
        )
        for event in events:
            print(f"#{event.seq} {event.ts} [{event.stage}] {event.kind}: "
                  f"{event.summary}")
            if args.verbose:
                print("    " + json.dumps(event.payload)[:800])
        return 0
    finally:
        store.close()


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

WIDGET_BUGGY = '''"""Demo widget (agent's first attempt: buggy, no strip)."""


def slugify(text):
    return text.lower().replace(" ", "-")
'''

WIDGET_TEST = '''"""Tests for the demo widget (written by the agent)."""

from babysitter.demo_widget import slugify


def test_slugify_strips_and_hyphenates():
    assert slugify("  Hello World  ") == "hello-world"
'''

WIDGET_FIX_OLD = '    return text.lower().replace(" ", "-")\n'
WIDGET_FIX_NEW = '    return text.strip().lower().replace(" ", "-")\n'


def _corrupt_unquoted_keys(args: dict) -> str:
    """Turn valid args into realistically malformed model output:
    unquoted keys + trailing comma (still healable)."""
    import re

    text = json.dumps(args, indent=2)
    text = re.sub(r'(?m)^  "([A-Za-z_]+)":', r"  \1:", text)
    text = text.replace("\n}", ",\n}")
    return text


def run_demo(keep_dir: str | None = None, quiet: bool = False) -> dict:
    """Build the demo target, run the supervised loop, return the report.

    Returns {"status": ..., "task_id": ..., "target": ..., "metrics": ...}.
    Raises SystemExit only via cmd_demo; this function itself returns data
    so tests can assert on it.
    """
    from .loop import LoopConfig, run_task
    from .metrics import global_metrics, task_metrics
    from .provider import ModelTurn, ScriptedProvider, ToolCall
    from .store import BabysitterStore

    here = Path(__file__).resolve().parent
    babysitter_root = here.parent.parent  # babysitter/
    if keep_dir:
        target = Path(keep_dir).resolve()
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
    else:
        target = Path(tempfile.mkdtemp(prefix="babysitter-demo-"))

    # The target is a REAL project slice: Babysitter's own schema/store +
    # their REAL test file. The agent adds a widget + its test to it.
    (target / "src" / "babysitter").mkdir(parents=True)
    (target / "tests").mkdir(parents=True)
    for name in ("__init__.py", "schema.py", "store.py"):
        shutil.copy(here / name, target / "src" / "babysitter" / name)
    shutil.copy(babysitter_root / "tests" / "conftest.py", target / "tests" / "conftest.py")
    # The copied conftest points sys.path at the target's own src/ (it is
    # relative to its own location).
    shutil.copy(
        babysitter_root / "tests" / "test_schema_store.py",
        target / "tests" / "test_schema_store.py",
    )
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(["git", "config", "user.email", "demo@babysitter.local"],
                   cwd=target, check=True)
    subprocess.run(["git", "config", "user.name", "babysitter-demo"], cwd=target,
                   check=True)
    subprocess.run(["git", "add", "."], cwd=target, check=True)
    subprocess.run(["git", "commit", "-qm", "demo baseline"], cwd=target, check=True)

    verify_cfg = {
        "test": [sys.executable, "-m", "pytest", "tests/test_schema_store.py",
                 "tests/test_demo_widget.py", "-q", "-p", "no:cacheprovider"],
        "typecheck": None,
        "timeout_s": 120,
    }
    (target / CONFIG_NAME).write_text(json.dumps(
        {"verify": verify_cfg, "ladder": ["demo-weak", "demo-strong"]}, indent=2))

    store = BabysitterStore(target / STATE_DIR / DB_NAME)
    task = store.create_task(
        goal="Add a slugify() helper in src/babysitter/demo_widget.py with "
        "tests in tests/test_demo_widget.py.",
        project_root=str(target),
        model="demo-weak",
        config={"ladder": ["demo-weak", "demo-strong"], "mode": "demo"},
    )

    widget_args = {"path": "src/babysitter/demo_widget.py", "content": WIDGET_BUGGY}
    test_args = {"path": "tests/test_demo_widget.py", "content": WIDGET_TEST}
    weak_script = [
        ModelTurn(content="I'll create the widget and its test.", tool_calls=[
            ToolCall(call_id="call-1", name="write_file",
                     args_raw=_corrupt_unquoted_keys(widget_args)),
            ToolCall(call_id="call-2", name="write_file",
                     args_raw="```json\n" + json.dumps(test_args, indent=2) + "\n```"),
        ]),
        ModelTurn(content="The test shows missing strip; fixing.", tool_calls=[
            ToolCall(call_id="call-3", name="edit_file", args_raw=json.dumps({
                "path": "src/babysitter/demo_widget.py",
                "old_text": WIDGET_FIX_OLD,
                "new_text": WIDGET_FIX_NEW,
            })),
        ]),
        ModelTurn(content="Done; the change is verified.", tool_calls=[]),
    ]
    strong_script = [ModelTurn(content="Done.", tool_calls=[])]
    providers = {
        "demo-weak": ScriptedProvider("demo-weak", weak_script),
        "demo-strong": ScriptedProvider("demo-strong", strong_script),
    }
    status = run_task(
        store, task.id, providers,
        LoopConfig(ladder=["demo-weak", "demo-strong"], verify=verify_cfg),
    )
    report = {
        "status": status,
        "task_id": task.id,
        "target": str(target),
        "metrics": task_metrics(store, task.id),
        "global_metrics": global_metrics(store),
    }
    if not quiet:
        print(f"demo target: {target}")
        print(f"task {task.id}: {status}")
        kinds = {}
        for event in store.list_events(task.id, limit=1000):
            kinds[event.kind] = kinds.get(event.kind, 0) + 1
        print("event counts: " + json.dumps(kinds, sort_keys=True))
        print("task metrics: " + json.dumps(report["metrics"], sort_keys=True))
        print(f"inspect: babysitter trace {task.id} --project-root {target}")
    store.close()
    return report


def cmd_demo(args: argparse.Namespace) -> int:
    report = run_demo(keep_dir=args.keep)
    if report["status"] == "verified_complete":
        print("DEMO PASSED: unreliable run -> verified task, no human involved.")
        return 0
    print(f"DEMO FAILED: terminal status {report['status']}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="babysitter",
        description="Babysitter: a local runtime supervisor for AI coding agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold babysitter.json + state dir")
    p_init.add_argument("--project-root", default=".")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_start = sub.add_parser("start", help="run the protocol server")
    p_start.add_argument("--project-root", default=".")
    p_start.add_argument("--host", default="127.0.0.1")
    p_start.add_argument("--port", type=int, default=8123)
    p_start.set_defaults(func=cmd_start)

    p_doctor = sub.add_parser("doctor", help="check supervision readiness")
    p_doctor.add_argument("--project-root", default=".")
    p_doctor.set_defaults(func=cmd_doctor)

    p_trace = sub.add_parser("trace", help="inspect tasks, events, metrics")
    p_trace.add_argument("task_id", nargs="?")
    p_trace.add_argument("--project-root", default=".")
    p_trace.add_argument("--limit", type=int, default=200)
    p_trace.add_argument("--stage", action="append", default=None)
    p_trace.add_argument("--kind", action="append", default=None)
    p_trace.add_argument("--metrics", action="store_true")
    p_trace.add_argument("--verbose", action="store_true")
    p_trace.set_defaults(func=cmd_trace)

    p_demo = sub.add_parser("demo", help="run the v0.1 acceptance demo")
    p_demo.add_argument("--keep", default=None,
                        help="keep the demo target at this path")
    p_demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Read-only local console. Separate from the execution/protocol trust boundary."""
from __future__ import annotations

import hmac
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Config
from .state import redact

WEB = Path(__file__).with_name("web")
LOCAL = {"localhost", "127.0.0.1", "::1"}
AGENTS = [
    {"id": "claude-code", "name": "Claude Code", "kind": "Native hooks", "description": "Observe native tools. Verify before completion. Recover with context.", "command": "aletheia claude install\naletheia claude status\nclaude", "note": "Review the installed commands in Claude Code /hooks before starting a fresh session."},
    {"id": "codex", "name": "Codex", "kind": "Native hooks", "description": "Guard patch paths and keep recovery in the same supervised task.", "command": "aletheia codex install\naletheia codex status\ncodex", "note": "Trust the project and review/trust the exact hook definitions in Codex /hooks. Permissions stay native."},
    {"id": "opencode", "name": "OpenCode", "kind": "Owned CLI process", "description": "Verify after the process exits. Retry in the same native session.", "command": "aletheia opencode status\naletheia opencode run 'Fix the failing tests'", "note": "Use this wrapper, not the normal TUI. No pre-tool interception, auto-approval, or plugin installation."},
]


def clean(value):
    """Redact known patterns and bound arbitrary native payload strings."""
    value = redact(value)
    if isinstance(value, str):
        return value[:64000] + ("\n[preview truncated]" if len(value) > 64000 else "")
    if isinstance(value, list):
        return [clean(v) for v in value[:5000]]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    return value


@contextmanager
def reader(root: Path):
    directory = root / ".aletheia"
    path = directory / "state.sqlite3"
    if directory.is_symlink() or path.is_symlink():
        raise HTTPException(409, "Symlinked runtime state is not served")
    if not path.exists():
        yield None
        return
    db = None
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        deadline = time.monotonic() + 5
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        yield db
    except (sqlite3.Error, ValueError):
        raise HTTPException(409, "Runtime evidence is unavailable or incompatible; inspect it with the CLI")
    finally:
        if db:
            db.close()


def events_for(db, task_id: str, limit: int = 5000) -> list[dict]:
    rows = db.execute("SELECT seq,id,schema_version,task_id,session_id,step_id,timestamp,stage,kind,attempt,model,substr(payload_json,1,4000001) AS payload_json FROM events WHERE task_id=? ORDER BY seq DESC LIMIT ?", (task_id, limit))
    result = []
    budget = 4_000_000
    for row in rows:
        event = dict(row)
        raw = event.pop("payload_json")
        if len(raw) > budget:
            break
        budget -= len(raw)
        event["payload"] = json.loads(raw)
        result.append(event)
    return list(reversed(result))


def summarize(task: dict, events: list[dict], checkpoints: list[dict]) -> dict:
    start: dict = next((e["payload"] for e in events if e["kind"] == "task.started"), {})
    evidence = [e for e in events if e["kind"] == "verification.result"]
    return {**task, "adapter": start.get("adapter", "protocol"), "checkpoint_count": len(checkpoints),
            "verification_count": len(evidence), "last_verification": evidence[-1]["payload"] if evidence else None}


def workspace(root: Path) -> dict:
    tasks: list[dict] = []
    activity: list[dict] = []
    counts = {"total": 0, "verified": 0, "active": 0, "failed": 0, "caught": 0, "checkpoints": 0}
    with reader(root) as db:
        if db:
            counts["total"] = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            counts["verified"] = db.execute("SELECT COUNT(*) FROM tasks WHERE state='verified_complete'").fetchone()[0]
            counts["failed"] = db.execute("SELECT COUNT(*) FROM tasks WHERE state IN ('failed','verification_unavailable')").fetchone()[0]
            counts["active"] = counts["total"] - counts["verified"] - counts["failed"]
            counts["checkpoints"] = db.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
            counts["caught"] = db.execute("SELECT COUNT(*) FROM events WHERE kind='verification.result' AND json_extract(payload_json,'$.status')='failed'").fetchone()[0]
            for row in db.execute("SELECT id,session_id,substr(goal,1,2000) AS goal,state,model,step_id,attempts,consecutive_failures,checkpoint_id,created_at,updated_at FROM tasks ORDER BY updated_at DESC LIMIT 100"):
                task = dict(row)
                # Only summary kinds, not potentially large tool transcripts.
                summary_events = []
                for kind, order in (("task.started", "ASC"), ("verification.result", "DESC")):
                    r = db.execute(f"SELECT payload_json FROM events WHERE task_id=? AND kind=? ORDER BY seq {order} LIMIT 1", (task["id"], kind)).fetchone()
                    if r:
                        payload = json.loads(r[0])
                        if kind == "verification.result":
                            payload = {"status": payload.get("status"), "commands": [{"name": c.get("name"), "exit_code": c.get("exit_code"), "timed_out": c.get("timed_out")} for c in payload.get("commands", [])[:20]]}
                        summary_events.append({"kind": kind, "payload": payload})
                summary = summarize(task, summary_events, [])
                summary["checkpoint_count"] = db.execute("SELECT COUNT(*) FROM checkpoints WHERE task_id=?", (task["id"],)).fetchone()[0]
                summary["verification_count"] = db.execute("SELECT COUNT(*) FROM events WHERE task_id=? AND kind='verification.result'", (task["id"],)).fetchone()[0]
                tasks.append(summary)
            for row in db.execute("SELECT * FROM events WHERE kind IN ('task.finished','verification.result','rollback.completed','retry.scheduled','checkpoint.created','failure') ORDER BY seq DESC LIMIT 8"):
                event = dict(row)
                event["payload"] = json.loads(event.pop("payload_json"))
                activity.append(event)
    config_path = root / "aletheia.json"
    if config_path.is_symlink():
        raise HTTPException(409, "Symlinked configuration is not served")
    try:
        if config_path.exists() and config_path.stat().st_size > 2_000_000:
            raise ValueError("Configuration too large")
        config = Config.load(root)
        commands = {"test": config.test_command, "typecheck": config.typecheck_command}
        config_error = None
    except (ValueError, OSError):
        commands, config_error = {}, "Configuration could not be read; use aletheia doctor --offline"
    return clean({"mode": "local", "version": __version__, "project": root.name, "root": str(root),
                  "stats": counts, "tasks": tasks, "tasks_truncated": counts["total"] > len(tasks), "activity": activity,
                  "config": {"initialized": config_path.is_file(), "commands": commands, "error": config_error},
                  "agents": [{**a, "observed": any(t["adapter"] == a["id"] for t in tasks)} for a in AGENTS]})


def detail(root: Path, task_id: str) -> dict:
    with reader(root) as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone() if db else None
        if not row:
            raise HTTPException(404, "Task not found")
        events = events_for(db, task_id)
        checkpoints = [dict(r) for r in db.execute("SELECT id,task_id,purpose,created_at FROM checkpoints WHERE task_id=? ORDER BY created_at", (task_id,))]
        count = db.execute("SELECT COUNT(*) FROM events WHERE task_id=?", (task_id,)).fetchone()[0]
        summary = summarize(dict(row), events, checkpoints)
        # A bounded event window might omit the original task.started.
        start = db.execute("SELECT payload_json FROM events WHERE task_id=? AND kind='task.started' ORDER BY seq LIMIT 1", (task_id,)).fetchone()
        if start:
            summary["adapter"] = json.loads(start[0]).get("adapter", "protocol")
        return clean({"schema_version": 1, "task": summary, "events": events, "events_truncated": count > len(events), "checkpoints": checkpoints})


def retained_path(root: Path, relative: str) -> Path:
    directory = root / ".aletheia" / "checkpoints"
    path = directory / relative
    for candidate in (root / ".aletheia", directory, *path.relative_to(directory).parents):
        candidate = candidate if candidate.is_absolute() else directory / candidate
        if candidate.is_symlink():
            raise HTTPException(409, "Symlinked evidence is not served")
    if path.is_symlink():
        raise HTTPException(409, "Symlinked evidence is not served")
    if not path.resolve().is_relative_to(directory.resolve()):
        raise HTTPException(404, "Checkpoint artifact not found")
    return path


def checkpoint(root: Path, task_id: str, checkpoint_id: str, filename: str | None) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", checkpoint_id):
        raise HTTPException(404, "Checkpoint not found")
    with reader(root) as db:
        row = db.execute("SELECT id,purpose,created_at FROM checkpoints WHERE id=? AND task_id=?", (checkpoint_id, task_id)).fetchone() if db else None
        if not row:
            raise HTTPException(404, "Checkpoint not found for this task")
    try:
        path = retained_path(root, checkpoint_id + ".json")
        if path.stat().st_size > 2_000_000:
            raise HTTPException(413, "Manifest too large for browser inspection; use the CLI")
        manifest = json.loads(path.read_text())["files"]
        if not isinstance(manifest, dict) or any(not isinstance(v, dict) or not isinstance(v.get("sha256"), str) for v in manifest.values()):
            raise ValueError("Invalid manifest")
        result = {**dict(row), "files": [{"path": name, **entry} for name, entry in list(manifest.items())[:1000]], "truncated": len(manifest) > 1000}
        if filename is not None:
            if filename not in manifest:
                raise HTTPException(404, "File is not in this checkpoint")
            digest = manifest[filename]["sha256"]
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise HTTPException(409, "Invalid retained content hash")
            blob = retained_path(root, "blobs/" + digest)
            with blob.open("rb") as f:
                data = f.read(64001)
            result["preview"] = "[Binary content — inspect with CLI]" if b"\x00" in data else data[:64000].decode(errors="replace")
            result["preview_truncated"] = len(data) > 64000
        return clean(result)
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(409, "Retained evidence is missing or malformed; no working-tree files were read")


def create_console(root: Path | str = ".", *, demo: bool = False, token: str | None = None) -> FastAPI:
    root = Path(root).resolve()
    token = token if token is not None else os.environ.get("ALETHEIA_UI_TOKEN")
    app = FastAPI(title="Aletheia local console", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    demo_state = None
    if demo:
        from .console_demo import create_demo
        demo_state = create_demo()

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if (origin and urlsplit(origin).netloc != request.url.netloc) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Same-origin console requests only"}, status_code=403)
            if not demo:
                supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
                if token and not hmac.compare_digest(supplied.encode(), token.encode()):
                    return JSONResponse({"detail": "Local console token required"}, status_code=401)
                if not token and request.url.hostname not in LOCAL:
                    return JSONResponse({"detail": "Non-loopback access requires ALETHEIA_UI_TOKEN"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get("/api/workspace")
    def get_workspace():
        return demo_state["workspace"] if demo_state else workspace(root)

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        if demo_state:
            if task_id not in demo_state["details"]:
                raise HTTPException(404, "Demo task not found")
            return demo_state["details"][task_id]
        return detail(root, task_id)

    @app.get("/api/tasks/{task_id}/checkpoints/{checkpoint_id}")
    def get_checkpoint(task_id: str, checkpoint_id: str, file: str | None = None):
        if demo_state:
            item = demo_state["checkpoints"].get((task_id, checkpoint_id))
            if not item or (file and file not in [f["path"] for f in item["files"]]):
                raise HTTPException(404, "Demo checkpoint not found")
            return {**item, **({"preview": "# Illustrative checkpoint content, not a project file.\ndef verify(result):\n    return result.status == 'passed'\n", "preview_truncated": False} if file else {})}
        return checkpoint(root, task_id, checkpoint_id, file)

    app.mount("/guides", StaticFiles(directory=WEB / "guides"), name="guides")
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    return app

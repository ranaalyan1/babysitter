"""Frozen v1 persistence envelope; payloads are extensible JSON objects."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

TaskState = Literal["observed", "validating", "repairing", "executing", "awaiting_tools", "verifying", "recovering", "escalating", "verified_complete", "verification_unavailable", "failed"]
Stage = Literal["observe", "validate", "repair", "execute", "verify", "recover", "escalate"]


class TaskRecord(TypedDict):
    id: str
    session_id: str
    goal: str
    plan_json: str
    state: TaskState
    model: str
    step_id: str
    consecutive_failures: int
    attempts: int
    checkpoint_id: str | None
    created_at: str
    updated_at: str


class EventRecord(TypedDict):
    seq: int
    id: str
    schema_version: Literal[1]
    task_id: str
    session_id: str
    step_id: str
    timestamp: str
    stage: Stage
    kind: str
    attempt: int
    model: str
    payload: dict[str, Any]


STAGES = {"observe", "validate", "repair", "execute", "verify", "recover", "escalate"}
TERMINAL = {"verified_complete", "verification_unavailable", "failed"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid.uuid4().hex


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(r"api.?key|authorization|password|secret|access.?token", k, re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"(?i)(bearer\s+|(?:api_key|password|secret|access_token)\s*[=:]\s*)[^\s,\"']+",
                      r"\1[REDACTED]", value)
    return value


class Store:
    def __init__(self, directory: Path, timeout: float = 5):
        if directory.is_symlink():
            raise ValueError("runtime state directory must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(directory / "state.sqlite3", timeout=timeout)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(Path(__file__).with_name("schema.sql").read_text())

    def create(self, goal: str, model: str, session_id: str | None = None) -> dict:
        task_id, timestamp = uid(), now()
        with self.db:
            self.db.execute("INSERT INTO tasks(id,session_id,goal,state,model,step_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                            (task_id, session_id or uid(), goal, "observed", model, uid(), timestamp, timestamp))
        return self.task(task_id)

    def task(self, task_id: str) -> dict:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return dict(row)

    def event(self, task_id: str, stage: str, kind: str, payload: dict, *, state: str | None = None,
              model: str | None = None, **updates: Any) -> None:
        assert stage in STAGES
        allowed = {"step_id", "consecutive_failures", "attempts", "checkpoint_id", "plan_json"}
        if updates.keys() - allowed:
            raise ValueError("invalid task update")
        task = self.task(task_id)
        if state:
            updates["state"] = state
        updates["updated_at"] = now()
        active_model = self.db.execute("SELECT model FROM events WHERE task_id=? AND step_id=? AND kind='model.request' ORDER BY seq DESC LIMIT 1",
                                       (task_id, task["step_id"])).fetchone()
        with self.db:
            self.db.execute("INSERT INTO events(id,schema_version,task_id,session_id,step_id,timestamp,stage,kind,attempt,model,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (uid(), 1, task_id, task["session_id"], task["step_id"], now(), stage, kind,
                             updates.get("attempts", task["attempts"]), model or (active_model[0] if active_model else task["model"]), json.dumps(redact(payload))))
            self.db.execute("UPDATE tasks SET " + ",".join(f"{key}=?" for key in updates) + " WHERE id=?",
                            (*updates.values(), task_id))

    def checkpoint(self, checkpoint_id: str, task_id: str, purpose: str, manifest: Path) -> None:
        with self.db:
            self.db.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?)", (checkpoint_id, task_id, purpose, str(manifest), now()))
        self.event(task_id, "execute", "checkpoint.created", {"checkpoint_id": checkpoint_id, "purpose": purpose,
                   "manifest_path": str(manifest)}, **({"checkpoint_id": checkpoint_id} if purpose == "baseline" else {}))

    def trace(self, task_id: str | None = None) -> dict:
        tasks = [dict(r) for r in self.db.execute("SELECT * FROM tasks" + (" WHERE id=?" if task_id else "") + " ORDER BY created_at",
                                                 (task_id,) if task_id else ())]
        events = []
        for row in self.db.execute("SELECT * FROM events" + (" WHERE task_id=?" if task_id else "") + " ORDER BY seq",
                                   (task_id,) if task_id else ()):
            event = dict(row)
            event["payload"] = json.loads(event.pop("payload_json"))
            events.append(event)
        checkpoints = [dict(r) for r in self.db.execute("SELECT * FROM checkpoints" + (" WHERE task_id=?" if task_id else ""),
                                                       (task_id,) if task_id else ())]
        return {"schema_version": 1, "tasks": tasks, "events": events, "checkpoints": checkpoints}

    def close(self) -> None:
        self.db.close()

"""SQLite-backed task / event / checkpoint store (the Observe stage's memory).

One database file per supervised project (``.babysitter/babysitter.db``).
The store enforces the frozen schema: unknown event kinds, wrong
stage-for-kind, and unknown task statuses are rejected with ValueError so
a producer bug can never silently corrupt the log.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from .schema import (
    DDL,
    EVENT_KINDS,
    KIND_STAGES,
    KIND_TASK_CREATED,
    KIND_TASK_STATUS,
    SCHEMA_VERSION,
    STAGE_OBSERVE,
    STATUS_OPEN,
    TASK_STATUSES,
    TERMINAL_STATUSES,
    Checkpoint,
    Event,
    Task,
    utcnow,
)

#: Payloads bigger than this are rejected — producers must truncate tails.
MAX_PAYLOAD_BYTES = 16 * 1024


def new_task_id() -> str:
    return "bst_" + uuid.uuid4().hex[:12]


def new_checkpoint_id() -> str:
    return "chk_" + uuid.uuid4().hex[:12]


class BabysitterStore:
    """Synchronous SQLite store. One writer (server/loop) + concurrent CLI
    readers; WAL mode keeps readers from blocking the writer."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Babysitter's own state must never pollute the project's git diff,
        # checkpoints, or rollbacks.
        gitignore = self.db_path.parent / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "# Babysitter runtime state (event log, checkpoints). "
                "Never commit.\n*\n"
            )
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(DDL)
        self._conn.commit()
        self._check_version()

    # -- schema version ----------------------------------------------------

    def _check_version(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
            return
        found = int(row[0])
        if found != SCHEMA_VERSION:
            raise RuntimeError(
                f"babysitter.db schema version is {found}, "
                f"this build speaks {SCHEMA_VERSION}; refusing to open."
            )

    def close(self) -> None:
        self._conn.close()

    # -- tasks ---------------------------------------------------------------

    def create_task(
        self, goal: str, project_root: str, model: str, config: dict
    ) -> Task:
        now = utcnow()
        task = Task(
            id=new_task_id(),
            goal=goal,
            project_root=project_root,
            status=STATUS_OPEN,
            created_at=now,
            updated_at=now,
            model=model,
            config=dict(config),
        )
        self._conn.execute(
            "INSERT INTO tasks(id, goal, project_root, status, created_at,"
            " updated_at, model, config_json) VALUES (?,?,?,?,?,?,?,?)",
            task.to_row(),
        )
        self._conn.commit()
        self.log_event(
            task.id,
            STAGE_OBSERVE,
            KIND_TASK_CREATED,
            f"task created: {goal[:120]}",
            {"goal": goal, "project_root": project_root, "model": model},
        )
        return task

    def get_task(self, task_id: str) -> Task | None:
        row = self._conn.execute(
            "SELECT id, goal, project_root, status, created_at, updated_at,"
            " model, config_json FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        return Task.from_row(row) if row else None

    def list_tasks(self, limit: int = 50) -> list[Task]:
        rows = self._conn.execute(
            "SELECT id, goal, project_root, status, created_at, updated_at,"
            " model, config_json FROM tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Task.from_row(r) for r in rows]

    def set_task_status(
        self, task_id: str, status: str, summary: str = "", payload: dict | None = None
    ) -> Task:
        if status not in TASK_STATUSES:
            raise ValueError(f"unknown task status: {status!r}")
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        if task.status in TERMINAL_STATUSES and status != task.status:
            raise ValueError(
                f"task {task_id} is terminal ({task.status}); "
                f"refusing transition to {status}"
            )
        now = utcnow()
        self._conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
            (status, now, task_id),
        )
        self._conn.commit()
        task.status = status
        task.updated_at = now
        self.log_event(
            task_id,
            STAGE_OBSERVE,
            KIND_TASK_STATUS,
            summary or f"status -> {status}",
            {"status": status, **(payload or {})},
        )
        return task

    def set_task_model(self, task_id: str, model: str) -> None:
        self._conn.execute(
            "UPDATE tasks SET model=?, updated_at=? WHERE id=?",
            (model, utcnow(), task_id),
        )
        self._conn.commit()

    # -- events (append-only) --------------------------------------------------

    def log_event(
        self,
        task_id: str,
        stage: str,
        kind: str,
        summary: str,
        payload: dict | None = None,
    ) -> Event:
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind: {kind!r} (schema is frozen)")
        expected_stage = KIND_STAGES[kind]
        if stage != expected_stage:
            raise ValueError(
                f"event kind {kind!r} belongs to stage {expected_stage!r}, "
                f"not {stage!r}"
            )
        payload = payload or {}
        payload_text = json.dumps(payload, sort_keys=True)
        if len(payload_text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"event payload exceeds {MAX_PAYLOAD_BYTES} bytes; "
                "producers must truncate tails"
            )
        if self.get_task(task_id) is None:
            raise KeyError(f"unknown task: {task_id}")
        cur = self._conn.execute(
            "INSERT INTO events(task_id, ts, stage, kind, summary, payload_json)"
            " VALUES (?,?,?,?,?,?)",
            (task_id, utcnow(), stage, kind, summary[:500], payload_text),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT seq, task_id, ts, stage, kind, summary, payload_json"
            " FROM events WHERE seq=?",
            (cur.lastrowid,),
        ).fetchone()
        return Event.from_row(row)

    def list_events(
        self,
        task_id: str,
        kinds: list[str] | None = None,
        stages: list[str] | None = None,
        limit: int = 500,
    ) -> list[Event]:
        sql = (
            "SELECT seq, task_id, ts, stage, kind, summary, payload_json"
            " FROM events WHERE task_id=?"
        )
        args: list = [task_id]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        if stages:
            sql += f" AND stage IN ({','.join('?' * len(stages))})"
            args.extend(stages)
        sql += " ORDER BY seq ASC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [Event.from_row(r) for r in rows]

    def count_events(self, task_id: str, kind: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE task_id=? AND kind=?",
            (task_id, kind),
        ).fetchone()
        return int(row[0])

    # -- checkpoints -----------------------------------------------------------

    def save_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        self._conn.execute(
            "INSERT INTO checkpoints(id, task_id, created_at, strategy, ref,"
            " status, reason) VALUES (?,?,?,?,?,?,?)",
            checkpoint.to_row(),
        )
        self._conn.commit()
        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        row = self._conn.execute(
            "SELECT id, task_id, created_at, strategy, ref, status, reason"
            " FROM checkpoints WHERE id=?",
            (checkpoint_id,),
        ).fetchone()
        return Checkpoint.from_row(row) if row else None

    def latest_active_checkpoint(self, task_id: str) -> Checkpoint | None:
        row = self._conn.execute(
            "SELECT id, task_id, created_at, strategy, ref, status, reason"
            " FROM checkpoints WHERE task_id=? AND status='active'"
            " ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return Checkpoint.from_row(row) if row else None

    def set_checkpoint_status(self, checkpoint_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE checkpoints SET status=? WHERE id=?", (status, checkpoint_id)
        )
        self._conn.commit()

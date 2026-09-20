"""Babysitter shared event / task-state schema, version 1 (FROZEN).

Every lifecycle stage (Observe / Validate / Repair / Execute / Verify /
Recover / Escalate) integrates through this schema and nothing else.
Producers append events; consumers read them. No stage reaches into
another stage's internals.

Frozen means: adding a new stage, event kind, task status, or table
requires a schema version bump and a migration note in docs/SCHEMA.md.
Do not extend casually.

Storage: SQLite (stdlib ``sqlite3``), one file per Babysitter project
(``.babysitter/babysitter.db``). Payloads are JSON text. Timestamps are
UTC ISO-8601 strings. IDs are ``bst_``- / ``chk_``-prefixed random hex.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Stages — the supervision lifecycle. One owner per stage; this is the
# vocabulary they share.
# ---------------------------------------------------------------------------

STAGE_OBSERVE = "observe"
STAGE_VALIDATE = "validate"
STAGE_REPAIR = "repair"
STAGE_EXECUTE = "execute"
STAGE_VERIFY = "verify"
STAGE_RECOVER = "recover"
STAGE_ESCALATE = "escalate"

STAGES: tuple[str, ...] = (
    STAGE_OBSERVE,
    STAGE_VALIDATE,
    STAGE_REPAIR,
    STAGE_EXECUTE,
    STAGE_VERIFY,
    STAGE_RECOVER,
    STAGE_ESCALATE,
)

# ---------------------------------------------------------------------------
# Event kinds — frozen set for schema v1. Payload contract per kind is
# documented in docs/SCHEMA.md and enforced by convention in store.log_event
# (unknown kinds are rejected so a typo can never corrupt the log).
# ---------------------------------------------------------------------------

KIND_TASK_CREATED = "task.created"
KIND_TASK_STATUS = "task.status"
KIND_MODEL_TURN = "model.turn"
KIND_TOOL_CALL_OBSERVED = "tool_call.observed"
KIND_TOOL_RESULT_OBSERVED = "tool_result.observed"

KIND_VALIDATION_PASSED = "validation.passed"
KIND_VALIDATION_FAILED = "validation.failed"

KIND_REPAIR_APPLIED = "repair.applied"
KIND_REPAIR_FAILED = "repair.failed"

KIND_TOOL_EXECUTED = "tool.executed"
KIND_TOOL_ERROR = "tool.error"

KIND_VERIFICATION_STARTED = "verification.started"
KIND_VERIFICATION_PASSED = "verification.passed"
KIND_VERIFICATION_FAILED = "verification.failed"
KIND_VERIFICATION_UNAVAILABLE = "verification.unavailable"

KIND_FAILURE_CLASSIFIED = "failure.classified"
KIND_CHECKPOINT_CREATED = "checkpoint.created"
KIND_ROLLBACK_DONE = "rollback.done"
KIND_RETRY_QUEUED = "retry.queued"
KIND_RETRY_EXHAUSTED = "retry.exhausted"

KIND_ESCALATION_TRIGGERED = "escalation.triggered"
KIND_ESCALATION_SKIPPED = "escalation.skipped"

EVENT_KINDS: frozenset[str] = frozenset(
    {
        KIND_TASK_CREATED,
        KIND_TASK_STATUS,
        KIND_MODEL_TURN,
        KIND_TOOL_CALL_OBSERVED,
        KIND_TOOL_RESULT_OBSERVED,
        KIND_VALIDATION_PASSED,
        KIND_VALIDATION_FAILED,
        KIND_REPAIR_APPLIED,
        KIND_REPAIR_FAILED,
        KIND_TOOL_EXECUTED,
        KIND_TOOL_ERROR,
        KIND_VERIFICATION_STARTED,
        KIND_VERIFICATION_PASSED,
        KIND_VERIFICATION_FAILED,
        KIND_VERIFICATION_UNAVAILABLE,
        KIND_FAILURE_CLASSIFIED,
        KIND_CHECKPOINT_CREATED,
        KIND_ROLLBACK_DONE,
        KIND_RETRY_QUEUED,
        KIND_RETRY_EXHAUSTED,
        KIND_ESCALATION_TRIGGERED,
        KIND_ESCALATION_SKIPPED,
    }
)

#: Which stage is allowed to emit which kind. The store enforces this.
KIND_STAGES: dict[str, str] = {
    KIND_TASK_CREATED: STAGE_OBSERVE,
    KIND_TASK_STATUS: STAGE_OBSERVE,
    KIND_MODEL_TURN: STAGE_OBSERVE,
    KIND_TOOL_CALL_OBSERVED: STAGE_OBSERVE,
    KIND_TOOL_RESULT_OBSERVED: STAGE_OBSERVE,
    KIND_VALIDATION_PASSED: STAGE_VALIDATE,
    KIND_VALIDATION_FAILED: STAGE_VALIDATE,
    KIND_REPAIR_APPLIED: STAGE_REPAIR,
    KIND_REPAIR_FAILED: STAGE_REPAIR,
    KIND_TOOL_EXECUTED: STAGE_EXECUTE,
    KIND_TOOL_ERROR: STAGE_EXECUTE,
    KIND_VERIFICATION_STARTED: STAGE_VERIFY,
    KIND_VERIFICATION_PASSED: STAGE_VERIFY,
    KIND_VERIFICATION_FAILED: STAGE_VERIFY,
    KIND_VERIFICATION_UNAVAILABLE: STAGE_VERIFY,
    KIND_FAILURE_CLASSIFIED: STAGE_RECOVER,
    KIND_CHECKPOINT_CREATED: STAGE_RECOVER,
    KIND_ROLLBACK_DONE: STAGE_RECOVER,
    KIND_RETRY_QUEUED: STAGE_RECOVER,
    KIND_RETRY_EXHAUSTED: STAGE_RECOVER,
    KIND_ESCALATION_TRIGGERED: STAGE_ESCALATE,
    KIND_ESCALATION_SKIPPED: STAGE_ESCALATE,
}

# ---------------------------------------------------------------------------
# Task statuses — the only terminal states that mean "done" are
# verified_complete (evidence exists) and rolled_back (changes reverted).
# A task is NEVER marked complete because the model said so.
# ---------------------------------------------------------------------------

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_VERIFIED_COMPLETE = "verified_complete"
STATUS_FAILED = "failed"
STATUS_ROLLED_BACK = "rolled_back"

TASK_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_OPEN,
        STATUS_IN_PROGRESS,
        STATUS_VERIFIED_COMPLETE,
        STATUS_FAILED,
        STATUS_ROLLED_BACK,
    }
)

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {STATUS_VERIFIED_COMPLETE, STATUS_FAILED, STATUS_ROLLED_BACK}
)

# ---------------------------------------------------------------------------
# Failure classes — the classifier's total output vocabulary.
# ---------------------------------------------------------------------------

FAILURE_TOOL_ERROR = "tool-error"
FAILURE_TEST_FAIL = "test-fail"
FAILURE_SYNTAX_FAIL = "syntax-fail"
FAILURE_NO_PROGRESS_LOOP = "no-progress-loop"
FAILURE_UNKNOWN = "unknown"

FAILURE_CLASSES: frozenset[str] = frozenset(
    {
        FAILURE_TOOL_ERROR,
        FAILURE_TEST_FAIL,
        FAILURE_SYNTAX_FAIL,
        FAILURE_NO_PROGRESS_LOOP,
        FAILURE_UNKNOWN,
    }
)

# ---------------------------------------------------------------------------
# Checkpoint strategies and statuses.
# ---------------------------------------------------------------------------

CHECKPOINT_GIT = "git-commit"  # scratch commit on a babysitter/ branch
CHECKPOINT_COPY = "file-copy"  # full tree copy under .babysitter/checkpoints

CHECKPOINT_STRATEGIES: frozenset[str] = frozenset({CHECKPOINT_GIT, CHECKPOINT_COPY})

CHECKPOINT_ACTIVE = "active"
CHECKPOINT_RESTORED = "restored"
CHECKPOINT_SUPERSEDED = "superseded"

CHECKPOINT_STATUSES: frozenset[str] = frozenset(
    {CHECKPOINT_ACTIVE, CHECKPOINT_RESTORED, CHECKPOINT_SUPERSEDED}
)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id          TEXT PRIMARY KEY,
  goal        TEXT NOT NULL,
  project_root TEXT NOT NULL,
  status      TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  model       TEXT NOT NULL,
  config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id     TEXT NOT NULL REFERENCES tasks(id),
  ts          TEXT NOT NULL,
  stage       TEXT NOT NULL,
  kind        TEXT NOT NULL,
  summary     TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(task_id, kind, seq);

CREATE TABLE IF NOT EXISTS checkpoints (
  id          TEXT PRIMARY KEY,
  task_id     TEXT NOT NULL REFERENCES tasks(id),
  created_at  TEXT NOT NULL,
  strategy    TEXT NOT NULL,
  ref         TEXT NOT NULL,
  status      TEXT NOT NULL,
  reason      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id, id);
"""

# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


def utcnow() -> str:
    """Current UTC time as an ISO-8601 string (the schema's timestamp format)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Task:
    id: str
    goal: str
    project_root: str
    status: str
    created_at: str
    updated_at: str
    model: str
    config: dict = field(default_factory=dict)

    def to_row(self) -> tuple:
        return (
            self.id,
            self.goal,
            self.project_root,
            self.status,
            self.created_at,
            self.updated_at,
            self.model,
            json.dumps(self.config, sort_keys=True),
        )

    @staticmethod
    def from_row(row: tuple) -> "Task":
        return Task(
            id=row[0],
            goal=row[1],
            project_root=row[2],
            status=row[3],
            created_at=row[4],
            updated_at=row[5],
            model=row[6],
            config=json.loads(row[7] or "{}"),
        )


@dataclass
class Event:
    seq: int
    task_id: str
    ts: str
    stage: str
    kind: str
    summary: str
    payload: dict = field(default_factory=dict)

    def to_row(self) -> tuple:
        return (
            self.task_id,
            self.ts,
            self.stage,
            self.kind,
            self.summary,
            json.dumps(self.payload, sort_keys=True),
        )

    @staticmethod
    def from_row(row: tuple) -> "Event":
        return Event(
            seq=row[0],
            task_id=row[1],
            ts=row[2],
            stage=row[3],
            kind=row[4],
            summary=row[5],
            payload=json.loads(row[6] or "{}"),
        )


@dataclass
class Checkpoint:
    id: str
    task_id: str
    created_at: str
    strategy: str
    ref: str
    status: str
    reason: str

    def to_row(self) -> tuple:
        return (
            self.id,
            self.task_id,
            self.created_at,
            self.strategy,
            self.ref,
            self.status,
            self.reason,
        )

    @staticmethod
    def from_row(row: tuple) -> "Checkpoint":
        return Checkpoint(
            id=row[0],
            task_id=row[1],
            created_at=row[2],
            strategy=row[3],
            ref=row[4],
            status=row[5],
            reason=row[6],
        )

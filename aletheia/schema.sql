-- Frozen event/task contract v1. See docs/SCHEMA.md.
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY CHECK(version = 1));
INSERT OR IGNORE INTO schema_version VALUES (1);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    plan_json TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL CHECK(state IN ('observed','validating','repairing','executing','awaiting_tools','verifying','recovering','escalating','verified_complete','verification_unavailable','failed')),
    model TEXT NOT NULL,
    step_id TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    checkpoint_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL CHECK(schema_version = 1),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    session_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('observe','validate','repair','execute','verify','recover','escalate')),
    kind TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    model TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_task_seq ON events(task_id, seq);
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    purpose TEXT NOT NULL CHECK(purpose IN ('baseline','failed_changes')),
    manifest_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

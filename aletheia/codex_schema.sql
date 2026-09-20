-- Additive Codex adapter contract v1; core event schema remains v1.
CREATE TABLE IF NOT EXISTS codex_adapter_version (
    version INTEGER PRIMARY KEY CHECK(version = 1)
);
INSERT OR IGNORE INTO codex_adapter_version VALUES (1);
CREATE TABLE IF NOT EXISTS codex_sessions (
    session_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id),
    model TEXT NOT NULL DEFAULT 'codex:unreported',
    prompt_id TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS codex_calls (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    tool_use_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','succeeded','failed','denied')),
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(task_id, tool_use_id)
);

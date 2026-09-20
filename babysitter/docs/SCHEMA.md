# Babysitter event / task-state schema v1 (FROZEN)

Status: **frozen**. This is the contract all seven lifecycle stages
integrate through. Changing it requires a schema version bump plus a
migration note appended at the bottom of this document — never a silent
edit.

Storage: SQLite, one file per supervised project at
`.babysitter/babysitter.db` (WAL mode, foreign keys on). DDL lives in
`src/babysitter/schema.py` (`DDL`) and is enforced by
`src/babysitter/store.py`:

- unknown event kinds are **rejected** (`ValueError`);
- a kind emitted under the wrong stage is **rejected**;
- unknown task statuses are **rejected**;
- terminal tasks (`verified_complete`, `failed`, `rolled_back`) refuse
  further status transitions;
- payloads larger than 16 KiB are **rejected** — producers truncate;
- a database with a different `schema_meta.version` is refused on open.

Conventions: timestamps are UTC ISO-8601 (`...T...:...` with offset);
IDs are `bst_<12 hex>` (tasks) and `chk_<12 hex>` (checkpoints);
`summaries` are one line, truncated to 500 chars; every `*_tail` payload
field is a truncated excerpt (producers should keep each under ~2000
chars).

## Tables

`tasks(id, goal, project_root, status, created_at, updated_at, model, config_json)`
`events(seq INTEGER PK AUTOINCREMENT, task_id, ts, stage, kind, summary, payload_json)`
`checkpoints(id, task_id, created_at, strategy, ref, status, reason)`
`schema_meta(key, value)` — single row `version = 1`.

Indexes: `events(task_id, seq)`, `events(task_id, kind, seq)`,
`checkpoints(task_id, id)`.

## Stages

`observe → validate → repair → execute → verify → recover → escalate`

## Task statuses

| status | meaning |
|---|---|
| `open` | created, loop not started |
| `in_progress` | loop running |
| `verified_complete` | terminal: model finished **and** verification passed (evidence in log) |
| `failed` | terminal: budget/step limit exhausted, nothing left to try |
| `rolled_back` | terminal: unrecoverable failure, tree restored to checkpoint |

## Event kinds and payload contracts

### observe

- `task.created` — `{goal, project_root, model}`
- `task.status` — `{status, ...}` (extra keys allowed, e.g. `reason`)
- `model.turn` — `{model, step, content_tail, tool_call_count, tool_call_names[]}`
- `tool_call.observed` — `{call_id, name, args_raw_tail}`
- `tool_result.observed` — `{call_id, name, ok, result_tail}`

### validate

- `validation.passed` — `{call_id, name}`
- `validation.failed` — `{call_id, name, issues[]}` where each issue is
  `{code, message}` with `code` in:
  `unknown-tool | bad-json | missing-field | extra-field | wrong-type |
  bad-path | path-escape | arg-too-large`

### repair

- `repair.applied` — `{call_id, name, fixes[], args_tail}` where `fixes[]`
  names each fix applied, e.g. `strip-fences | close-brackets |
  quote-keys | fix-literals | drop-trailing-commas | coerce:<field> |
  default:<field>`
- `repair.failed` — `{call_id, name, reason}`

### execute

- `tool.executed` — `{call_id, name, duration_ms, result_tail}`
- `tool.error` — `{call_id, name, error_tail}`

### verify

- `verification.started` — `{trigger, files_changed[]}` where `trigger`
  is `post-change | final | manual`
- `verification.passed` — `{checks[], files_changed[], insertions,
  deletions}` where each check is `{name, passed, command, exit_code,
  duration_ms}` and `files_changed[]` is `{path, added, deleted}`
- `verification.failed` — same as `passed`, plus `{failed_check, tail}`
- `verification.unavailable` — `{reason}` (surfaced, never hidden)

### recover

- `failure.classified` — `{class, evidence_tail, step}` where `class` is
  `tool-error | test-fail | syntax-fail | no-progress-loop | unknown`
- `checkpoint.created` — `{checkpoint_id, strategy, ref}`
- `rollback.done` — `{checkpoint_id, strategy, ref}`
- `retry.queued` — `{step, attempt, reason_tail, model}`
- `retry.exhausted` — `{step, attempts}`

### escalate

- `escalation.triggered` — `{from_model, to_model, step,
  consecutive_failures}`
- `escalation.skipped` — `{reason, step}` (e.g. `no-stronger-model`,
  `budget-exhausted`)

## Failure classes

`tool-error` (tool raised / timed out), `test-fail` (test command
failed), `syntax-fail` (typecheck/lint/parse failed),
`no-progress-loop` (same failing action repeated), `unknown` (total
fallback — the classifier always returns one of these five).

## Checkpoint strategies

`git-commit` (scratch commit on a `babysitter/<task>` branch; `ref` is
the commit SHA) or `file-copy` (full tree copy; `ref` is the copy path).
Checkpoint statuses: `active | restored | superseded`.

## Migration log

- v1 (initial): tables `tasks`, `events`, `checkpoints`, `schema_meta`;
  7 stages, 22 event kinds, 5 task statuses, 5 failure classes.

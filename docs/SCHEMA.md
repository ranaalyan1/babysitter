# Shared supervision contract — v1 (frozen)

Schema version: **1**. This contract is defined before feature code. SQLite DDL is
`babysitter/schema.sql`; typed representations are in `babysitter/state.py`.
Breaking changes require a migration and a new schema version. JSON payloads may
add fields; consumers must ignore unknown fields. No silent event rewrites.

## Task

`id`, `session_id`, `goal`, observed `plan_json` (never an invented hidden plan),
`state`, base `model`, `step_id`, `consecutive_failures`, `attempts`,
`checkpoint_id`, UTC `created_at` / `updated_at`.

States: observed → validating → [repairing] → executing → awaiting_tools or
verifying → verified_complete / verification_unavailable. Any failed stage →
recovering → [escalating] → validating; exhausted budget → failed.

A step is one tool batch plus its verification, or one terminal answer plus its
verification. Escalation counts consecutive failures **on that step**, resets
only after passing evidence, and never changes the task's base model.
`verified_complete` requires available, passing test AND typecheck commands plus
successful git-diff inspection, no pending tool calls, and no project content
changes during checks. `verification_unavailable` is explicitly NOT success.

## Append-only event envelope

`seq` (SQLite ordered cursor), `id` (UUID), `schema_version=1`, `task_id`,
`session_id`, `step_id`, UTC `timestamp`, `stage`, `kind`, `attempt`, `model`,
`payload_json` (JSON object). Event + task-state updates are transactional.
Stages are lifecycle stages, not infrastructure layers.

Payload kinds (minimum contracts):

| Stage | kind | Payload |
| --- | --- | --- |
| observe | task.started | goal, visibility, plan |
| observe | protocol.request | protocol, messages, tools; secrets redacted |
| observe | model.response | tool_calls, content |
| observe | client.tool_result | tool_call_id, result, error |
| validate | tool.valid / tool.invalid | tool, call_id, [errors] |
| repair | tool.repaired | tool, call_id, before, after, repairs |
| execute | tool.result | tool, call_id, result |
| execute | checkpoint.created | checkpoint_id, purpose, manifest_path |
| verify | verification.result | status, commands[], diff, files, fingerprint, reason |
| recover | failure | class, context, consecutive_failures |
| recover | rollback.completed | baseline_id, failed_changes_id, files |
| recover | retry.scheduled | instruction, next_model |
| escalate | model.escalated | from_model, to_model, failures |
| observe | step.advanced | previous_step_id, next_step_id |
| observe | task.finished | state, elapsed_seconds |

Failure classes: `tool-error`, `test-fail`, `syntax-fail`, `no-progress-loop`,
`verification-unavailable`, `provider-error`, `unsafe-change`.
Evidence command: argv, exit_code (nullable), stdout, stderr, duration_seconds,
timed_out, output_truncated. Git evidence: base and current fingerprints,
changed filenames, bounded diff, diff_truncated; includes nonignored untracked
files. Commands are configured by the local operator, never invented by a model.

## Checkpoints

`id`, `task_id`, `purpose` (`baseline` / `failed_changes`), `manifest_path`, UTC
`created_at`. Content-addressed file blobs + path/mode manifest are on local disk.
A failed-changes snapshot MUST be durable before restoring a baseline. Snapshot
failure aborts rollback; no unrecorded discard. Preexisting dirty/untracked files
are part of the baseline. Git index is not modified by rollback.

## Visibility and trust boundary

Only protocol messages/tool declarations/results and independent project checks
are observable. No claim of IDE internals, hidden plans, or external tool
execution visibility. In relay mode, caller must return the task header on each
request, execute clean tool calls, and report results. In managed mode, only
explicitly enabled local `read_file` / `write_file` calls run inside Babysitter.
A process-wide project lock serializes requests, not external editors.

## Contract review (implementation self-review, not user approval)

- Validate and verify are separate stages; only verify supplies completion proof.
- Retries, repairs, commands, failures, escalation and rollback have event records.
- Checkpoints preserve unsuccessful changes for trace inspection.
- Unavailable verification cannot increment task-success metrics.
- Session / task / step identities are distinct; protocol continuation is explicit.
- No hidden observations, credentials, provider routing or dashboard fields.

Frozen before verification/repair implementation. External review remains open.

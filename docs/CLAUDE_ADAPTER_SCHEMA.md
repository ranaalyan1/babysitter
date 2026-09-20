# Claude Code adapter contract — extension v1

This additive contract is defined before the adapter implementation. It preserves
`schema.sql` and the frozen core event envelope at version 1. New event kinds are
additive payloads, not a rewrite of the core schema. Implementation self-review:
completed; external review remains pending.

## Explicit expansion authorized

One opt-in Claude Code adapter using official **command hooks**. No new model
provider, orchestration, dashboard, proxy routing, or unofficial authentication.
Claude owns the model, tool execution, permission prompts, and conversation.
Aletheia owns checkpoints, independent verification and completion evidence.

## Persistent adapter tables (`claude_schema.sql`)

- `claude_sessions`: native `session_id` primary key; nullable current `task_id`
  referencing the core task; last reported `model`; optional `prompt_id`; UTC
  `updated_at`. SessionStart alone is not a completed task or a success metric.
- `claude_calls`: composite key (`task_id`, `tool_use_id`); `tool_name`;
  canonical/redacted `input_json`; state `pending | succeeded | failed | denied`;
  optional redacted `result_json`; timestamps. Pre/post hook correlation is
  persisted across separate CLI processes and overlapping hook invocations.
- `claude_adapter_version`: exactly version 1. No changes to core state names.

## Hook lifecycle

`SessionStart` registers the native session and injects factual supervision context.
`UserPromptSubmit` starts one task per user turn and takes a baseline checkpoint
before tools execute. An explicit new user prompt may supersede an unfinished
turn, preserving its bytes and recording failure rather than silently discarding.

`PreToolUse` validates the callback and supported native tool arguments, checks
workspace file paths, optionally returns `updatedInput`, and records pending
execution. It never returns `permissionDecision: allow`: native permissions remain
in control. Denials use the official nested `permissionDecision: deny` shape.
`PostToolUse` and `PostToolUseFailure` record actual callback-visible results.
They do not pretend a post hook can undo an already executed external command.

`Stop` runs test + typecheck + git-diff against the turn baseline only after all
observed calls have results and no reported background work remains. Multi-file
changes are checked together, not rejected after every partial edit. Failed checks
are checkpointed and rolled back, then `decision: block` feeds evidence to Claude.
After rollback, an unchanged baseline cannot count as a repaired task. A retry
must produce new observable changes before it can be verified complete.

For native tasks, the core `attempts` field counts Stop verification attempts,
not model invocations (which hooks do not fully observe). Event payloads identify
`adapter=claude-code`; model-selection metrics do not infer native model usage.

Stop retries are capped at min(config.max_attempts, 3), below Claude's documented
continuation cap. Exhaustion/unavailable checks/internal errors return
`continue: false` with a visible **NOT VERIFIED** reason and persist a non-success
state. `stop_hook_active: true` never bypasses checks. Native model escalation is
an explicit request to the operator, not a fabricated automatic model switch.

`SessionEnd` closes unfinished tasks as failed and preserves their bytes. It does
not roll back after exit: other tools/editors may still be operating.

## Additional core event payloads

- `task.started`: `adapter=claude-code`, native prompt identity, visibility,
  hashes of aletheia.json and local/project Claude settings, goal, plan=[]
- `claude.hook`: hook name, native session/tool identifiers, reported metadata
- `claude.tool.pending` / `tool.result`: call ID, tool, inputs/result, observation scope
- `claude.prompt.superseded` / `claude.session.ended`: reason, retained checkpoint
- `claude.plan.observed`: explicit tool-provided plan; never hidden reasoning
- `escalation.requested`: consecutive failure count, `automatic_model_switch=false`
- Existing `tool.valid`, `tool.invalid`, `tool.repaired`, `verification.result`,
  `failure`, `rollback.completed`, `retry.scheduled`, `task.finished` retain their
  lifecycle meanings and remain consumable by `aletheia trace`.

## Trust/visibility review

- Official docs: https://code.claude.com/docs/en/hooks (consulted 2026-09-20).
- Invalid native tool arguments may be rejected by Claude **before any hook**.
  This adapter cannot observe/repair those. The protocol adapter remains separate.
- Command-hook crashes/missing interpreters/timeouts can be non-blocking in Claude.
  Generated shell wrappers convert process errors to exit 2; internal deadlines
  precede configured hook deadlines, but externally killed/disabled hooks cannot
  be guaranteed fail-closed. Check installation with `/hooks` and adapter status.
- File-tool paths are guarded. Arbitrary shell/MCP semantics are delegated to
  Claude permissions and OS isolation, not falsely labeled sandboxed.
- Subagents and intentional background execution are not supervised by this first
  adapter. Single main-thread, dedicated-worktree operation is the supported mode.
- The same runtime.lock serializes hook processes and excludes the protocol server.
  It does not lock out editors. No concurrent-writer safety claim.
- Frozen control-file hashes prevent changed verification config from executing
  during a turn when the next hook still runs. Disabling/removing hooks outside
  Aletheia remains beyond this hook's enforcement boundary.

# v0.3 adapter contract — Codex + OpenCode

Defined before implementation; core task/event schema stays frozen at v1. Scope:
two opt-in single-agent integrations. DeepSeek and unnamed agents are deferred.
No model routing, new provider SDK, multi-agent orchestration or web service.

## Capabilities (not interchangeable)

| Adapter | Observation | Pre-action gate | Completion/recovery |
| --- | --- | --- | --- |
| Claude Code (existing) | native command hooks | native path/input guards; permissions remain native | Stop verification and bounded continuation |
| Codex | official native command hooks | `Bash`, `apply_patch` paths, observed local tools; no auto-approval/input rewrite | Stop verification; correlate generated continuation to the SAME task |
| OpenCode | owned `opencode run --format json` child process | native OpenCode permissions only; no claim of tool interception | process quiescence + real checks; `--session ID` retry; only wrapper exit 0 means verified |

## Persistence

Codex gets additive `codex_sessions` / `codex_calls` tables matching the native
hook envelope with separate ownership. v0.2 Claude tables are not renamed or
migrated. Shared hook lifecycle code is reused, not copied into a new agent loop.
Events keep their lifecycle stage and core envelope; `task.started.adapter`
distinguishes `claude-code`, `codex`, and `opencode`.

Codex Stop `decision: block` generates a user prompt. A persisted
`codex.stop.blocked.instruction` exact match (including pending-tool blocks) allows that continuation to retain its
original task/checkpoint/failure budget. An actual different user prompt starts a
new task and records the unfinished prior task as superseded. No hidden resets.

OpenCode creates one task before starting the native process. `opencode.event`
records the supported JSONL envelope; `tool.result` records emitted tool results,
not a made-up pre-execution event. Native `sessionID` is captured from events,
validated, and reused only for this task. The runner holds the project lock for
its entire run. Attempts count owned CLI invocations. Completion requires clean
process exit, well-formed emitted stream ending in a paired final stop step, no reported tool/process errors,
and passing test/typecheck/git-diff evidence.

## Failure and permission rules

- Codex input rewrite requires `permissionDecision: allow` in the documented
  interface. This adapter does not return allow or auto-approve. Inputs needing
  repair are denied with corrective context instead.
- Codex `apply_patch` must have a well-formed patch envelope and every add/update/
  delete/move destination must be in the supervised workspace, not control files.
- Codex PostToolUse also covers nonzero command exits. Explicit errors are logged;
  unknown result text is not converted into a fictitious success guarantee.
- Hook errors return event-specific blocking output. Codex SessionEnd/Interrupt
  are advisory and limited to three seconds; keep teardown bookkeeping lightweight.
- OpenCode JSONL, stderr and process lifetime are bounded. Timeout, interruption,
  malformed/truncated stream or unavailable checks never produce success. Kill
  the owned process group before inspecting/restoring changes.
- Failed checks: save unsuccessful contents, restore baseline, feed evidence to
  the same agent session. An unchanged rolled-back baseline cannot earn success.
- Configuration/control files are pinned for each task. A change halts supervision
  rather than executing weakened commands. Secrets in child environment belong
  to the native agent; verification receives only the existing safe allowlist.
- No adapter switches the native agent's model. Escalation requests are distinct
  from actual model-switch metrics.
- One supervisor/agent per worktree. No simultaneous proxy/native supervision.

## Installation and evidence

Codex install merges `.codex/hooks.json`, backs it up, preserves unrelated entries,
and is reversible/idempotent. It does not change Codex config, permissions, trust,
credentials, or sandbox flags. Users review/trust project + hooks in Codex.
OpenCode uses a wrapper command; no plugin or global configuration is installed.

Required validation: contract regressions, real filesystem/check commands,
negative completion cases, and official native CLI runs against clearly labeled
local scripted model endpoints where possible. These are not real-model quality
or market superiority claims. No auth scraping.

References consulted 2026-09-20:
- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://opencode.ai/docs/cli/
- https://opencode.ai/docs/plugins/

Implementation self-review: separate observe vs gate capabilities; no hook trust
bypass in production installation; no new cloud dependencies; no fabricated
pre-tool visibility; native model ownership excluded from base-model-only claims.

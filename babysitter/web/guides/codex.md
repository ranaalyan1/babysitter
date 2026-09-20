# Codex native hooks — v0.3

Tested with official **codex-cli 0.155.1**. This is a project-local hook adapter,
not a replacement Codex agent, model provider, app-server gateway or sandbox.

## Setup

Use a dedicated git worktree with at least one commit. Install Babysitter into a
stable Python 3.11+ virtualenv and install/authenticate Codex using its official
instructions. In the target repository:

```sh
babysitter init --test 'python -m pytest -q' --typecheck 'python -m mypy src'
# If already initialized, edit babysitter.json explicitly instead.
babysitter doctor --offline
babysitter codex install
babysitter codex status
codex
# Trust the project and review/trust the exact installed commands in /hooks.
# Then start a fresh supervised prompt/session.
```

No proxy server or Babysitter provider credentials are needed. Your normal Codex
model, authentication, permissions and sandbox stay authoritative. Installation
does **not** grant hook trust or disable permission/sandbox checks. `status` checks
local configuration, not Codex's private trust state or global feature settings.
Untrusted, globally disabled, or externally replaced hooks will not supervise.
Review hooks again after reinstalling or changing commands/interpreter paths.

Remove only Babysitter's marked entries, after ending the session:

```sh
babysitter codex uninstall
```

The installer merges `.codex/hooks.json`, preserves unrelated entries, and saves
private backups in `.babysitter/`. Reinstall is idempotent. `.codex/config.toml`,
credentials and unrelated settings are not modified. Explicit project-level
`features.hooks = false` is rejected rather than overridden.

## What happens

1. SessionStart records the native-reported model. UserPromptSubmit owns one task
   and checkpoints the existing worktree, including pre-existing uncommitted work.
2. PreToolUse observes supported native callbacks. Bash argument shape and obvious
   unsupported execution are guarded; `apply_patch` validates every add/update/
   delete/move path, including rename destinations and protected agent settings.
3. Valid tool calls return no approval override. Inputs needing coercion are
   **denied with corrective context**: Codex rewrites require `allow`, which this
   adapter deliberately never emits. Native results and explicit errors are logged.
4. Stop requires independent test + typecheck + git-diff checks and stable file
   evidence. Failed contents are checkpointed before rollback, then failure
   context is returned to Codex. Maximum Stop attempts: `min(max_attempts, 3)`.
5. A generated continuation, if delivered as UserPromptSubmit, must exactly match
   the persisted `codex.stop.blocked.instruction`; it retains the original task,
   checkpoint and budget. A different real user prompt explicitly supersedes the
   old task without discarding its work. The tested CLI continues inside one turn;
   separate-prompt correlation is also covered by contract regressions.

Pending/running tools prevent verification and rollback. An unchanged restored
baseline cannot earn success after a failed patch. Interrupt/SessionEnd are
advisory, at most three seconds: bounded bookkeeping, no test runs or snapshots,
and unfinished work is retained as not verified. Escalation requests are logged
for the operator, never counted as an actual native model switch.

## Trust boundary and evidence

**Native exit code 0 or “done” text is not proof of verification.** Look for
Babysitter's verified completion and inspect the task record:

```sh
babysitter trace
babysitter trace TASK_ID
babysitter trace TASK_ID --metrics
babysitter trace TASK_ID --checkpoint CHECKPOINT_ID
```

Hooks are guardrails, not a hard fail-closed security boundary. Disabled hooks,
missing executables, platform timeouts, hosted/specialized tools, shell semantics,
escaped/background processes and concurrent work can exceed their coverage.
Do not run subagents, background work, another supervisor or a second agent in
this worktree. Do not edit native/supervision configuration during a task.
Snapshot scope excludes ignored/generated files. Passing checks proves those
checks, not arbitrary natural-language goal satisfaction or resistance to
malicious changes to tests. Global native configuration is not managed here.

## Reproduce the official-client test

```sh
python scripts/native_agents_demo.py codex --executable /absolute/path/to/codex \
  --output .babysitter/codex-report.json
BABYSITTER_CODEX_BIN=/absolute/path/to/codex pytest -q tests/test_native_agents.py
```

This uses actual Codex tools/hooks with an isolated home and a local **scripted
Responses endpoint**, no real model or inherited credentials. The fixture names a
known model solely to select Codex tool metadata, not to claim a real model ran.
Only this disposable test explicitly uses `--dangerously-bypass-hook-trust` for
its generated hooks; the production installer never uses that flag. Native
workspace-write sandbox remains enabled. Captured [small-fixture results](codex-demo-results.json)
and [ItsDangerous upstream-suite results](codex-real-project-results.json).

See [shared adapter contract](ADAPTERS_V03_CONTRACT.md) and the
[official hook contract](https://learn.chatgpt.com/docs/hooks).

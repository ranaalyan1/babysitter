# Claude Code supervision — Babysitter v0.2

This is the first explicitly approved expansion beyond the v0.1 protocol runtime:
**one native Claude Code adapter**, built on official command hooks. No new
provider, dashboard, agent orchestrator, or unofficial authentication was added.

## What it does

```text
User prompt → baseline checkpoint
  → Claude proposes tool → PreToolUse validation/path guard
  → Claude executes under its OWN permissions
  → PostToolUse / PostToolUseFailure records actual result
  → Claude tries to finish → Stop runs tests + typecheck + git-diff
       FAIL → save failed contents → rollback → block with failure evidence
       PASS → record verified_complete → allow completion
```

Unlike protocol relay, **no task headers, proxy base URL, or running Babysitter
HTTP server are required**. Session IDs and tool-use IDs come from native hooks.
A task is one user-prompt turn; a session can contain multiple tasks.

Supported/tested environment: POSIX, Python 3.11+, Git repository root with a commit,
**Claude Code 2.1.278**. This is a terminal Claude Code integration; other surfaces
that honor the same project hooks may work but were not separately tested.

## Install in your project

Install Babysitter into an environment that remains on disk, then run from your
target repository. `init` is needed only if `babysitter.json` does not exist:

```sh
babysitter init \
  --test '/absolute/path/to/project/.venv/bin/python -m pytest -q' \
  --typecheck '/absolute/path/to/project/.venv/bin/python -m mypy src'

babysitter doctor --offline
babysitter claude install
babysitter claude status
claude
```

Replace the commands with your project's actual checks. Absolute executable paths
avoid differences between your shell and Claude's environment. For JS/TS projects,
argv commands such as `npm test -- --run` and `npm run typecheck` are fine if they
are the real project checks and `npm` is on Claude's PATH.

In Claude Code, inspect **`/hooks`** and confirm the Babysitter handlers are active.
Start a fresh session after installation. Keep Claude's normal permissions in
place; the adapter never auto-approves them or enables bypass mode.

`init` still writes provider fields for the protocol server. The native adapter
**does not use those fields to call a model**. Claude uses its own official
installation, authentication and selected model; no extra credentials are needed
by Babysitter. Do not run `babysitter start` in the same worktree while using hooks.

### Reversible installation

`babysitter claude install` merges seven command hooks into
`.claude/settings.local.json`:

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `Stop`
- `SessionEnd`

It preserves unrelated settings, permission rules and hooks; makes a durable
backup under `.babysitter/install-backups/`; uses quoted absolute interpreter/root
paths; and is idempotent. It refuses symlinked settings paths or a project with
hooks explicitly disabled. It doesn't modify global Claude settings or CLAUDE.md.

```sh
babysitter claude status      # inspect local installation, timeout, executable
babysitter claude uninstall   # remove only Babysitter's marked hooks
```

End the supervised Claude session before uninstalling. Evidence/checkpoints are
retained. If you move the repository/virtualenv or change command timeouts, rerun
`install` and start a fresh Claude session. The generated commands intentionally
reference the installed environment, not whichever `python` is on a future PATH.

## Completion guarantees and recovery

- Multi-file patches are verified together at **Stop**, not after each partial
  edit. Post-tool hooks observe results; they don't claim a partial edit is complete.
- Tests, typecheck and git-diff must pass. A final model statement is not evidence.
- Before rollback, failed contents are durably checkpointed and inspectable with
  `babysitter trace TASK_ID --checkpoint CHECKPOINT_ID`.
- After rollback, the unchanged baseline cannot count as a corrected task, even
  when its tests pass. A retry needs observable corrected changes.
- `stop_hook_active: true` **does not** bypass verification.
- Stop retries are bounded at **min(max_attempts, 3)**, below Claude's documented
  continuation limit. Exhaustion, unavailable checks or unsafe state yields a
  visible **NOT VERIFIED** halt, not a silent release or infinite retry loop.
- Two consecutive failures emit an `escalation.requested` event. The operator may
  use Claude's model selector for a harder step. The adapter **does not** claim to
  switch models automatically. The existing protocol runtime still supports its
  configured automatic, step-only escalation rule.
- Control-file hashes pin `babysitter.json`, `.gitignore`, and local/project Claude
  settings for a turn. If they change, the next hook halts instead of running new,
  potentially weakened verification commands. A new explicit user prompt can
  begin a task under the newly reviewed configuration.
- The core v1 event schema is preserved. Additive native session/call tables
  correlate callbacks across independent hook processes. See the
  [adapter contract](CLAUDE_ADAPTER_SCHEMA.md).

`babysitter trace` includes prompts, observed calls/results, explicit plan-tool
output (when supplied), check evidence, rollback and decisions. It never invents
hidden plans or reads the private transcript to infer facts. Tool output and local
snapshots may contain sensitive source data; keep `.babysitter` private.

## Real-agent evidence

The **official Claude Code CLI 2.1.278 actually executed** the adapter—not only
handcrafted HTTP requests or direct function calls. The test used a local scripted
Anthropic Messages endpoint to avoid credentials and make the failure repeatable:

1. Claude native `Read`, then native `Write` applies incorrect code.
2. Claude tries to finish. Stop runs real pytest, mypy and git checks.
3. Pytest fails. Babysitter preserves failed bytes, restores baseline, and sends
   the failure/rollback notice through Claude's real Stop-hook feedback path.
4. Claude native `Read`, then native `Write` applies the correction.
5. The next Stop checks pass and the native task becomes `verified_complete`.

Observed: **6 native model requests, 4 observed native tool results, 1 failure
caught, 1 verified task, 0 human interventions during the run**.
The API provider was scripted: **no real Claude model's coding capability, cost,
weak-model success rate, or market superiority was measured**.

[Captured command evidence and results](claude-demo-results.json)

Reproduce with an officially installed Claude Code executable:

```sh
pip install -e '.[dev]'
python scripts/claude_demo.py --claude /path/to/claude \
  --output .babysitter/claude-demo-report.json

# Includes the optional real-CLI regression in the full test suite:
BABYSITTER_CLAUDE_BIN=/path/to/claude pytest -q
mypy babysitter scripts/demo.py scripts/claude_demo.py
```

The script creates a disposable repository, isolated Claude configuration, and a
local model fixture. It does not read your Claude credentials or make real model
API calls. Its test-only Read/Write permission allowlist is explicit and scoped
to the disposable run; the installed adapter does not grant these permissions.
Without `BABYSITTER_CLAUDE_BIN`, the real-CLI test is skipped, not mislabeled passed.

## Honest boundaries

1. **Hooks are not a security sandbox.** Native file-tool paths are guarded;
   arbitrary Bash/MCP semantics still rely on Claude permissions and OS isolation.
   Bash commands execute in Claude, not Babysitter's shell-command allowlist.
2. **Single main-thread foreground work only.** Subagent/Agent/Task delegation,
   scheduled jobs and explicitly backgrounded commands are denied by this first
   adapter. Pending callback results or reported background work block completion.
   Out-of-order foreground tool results are correlated by ID, not assumed serial.
3. Native malformed/unknown tool calls can be rejected **before hooks run**; those
   failures are invisible here. `updatedInput` only repairs recoverable fields
   that actually reach a hook. v0.1 protocol JSON repair remains a separate mode.
4. Post hooks run after execution; they cannot hide or prevent already performed
   effects. A missing post event (including some permission-denial paths) isn't
   invented as success. Repeated unresolved results halt without rollback.
5. Only the **last reported** SessionStart model is observed. Native model
   selection is agent-owned; metrics exclude these tasks from base-model-only
   claims. A requested escalation is not counted as an actual model switch.
6. Use a **dedicated worktree**. The process lock serializes Babysitter callbacks
   and excludes the protocol server; it cannot stop an external editor. Stale
   evidence pauses rather than rolling back potentially concurrent changes.
7. **Claude can ignore disabled, missing or timed-out command hooks.** Generated
   shell wrappers convert process-launch failures to blocking exit 2, and internal
   timeouts precede installed hook deadlines. Nevertheless a platform-killed or
   disabled hook cannot guarantee fail-closed behavior. `/hooks`, status checks,
   native debug logs and the persisted task state matter. Babysitter never records
   verified completion when its verification did not run.
8. Editing/removing the hooks through another process can disable the next check.
   Hash guards detect changes only while hooks still run. This is not hardened
   against a malicious same-user process. Protect the environment externally if
   that is your threat model.
9. Passing configured checks proves those checks—not every natural-language
   requirement, not full test coverage, and not superiority over other products.

Official interface reference consulted: [Claude Code hooks](https://code.claude.com/docs/en/hooks),
particularly PreToolUse decision control, PostToolUse/Failure, Stop, exit codes
and timeout semantics. The tested version is recorded above; future versions may
change those semantics.

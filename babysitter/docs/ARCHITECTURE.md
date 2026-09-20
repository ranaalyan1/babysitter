# Babysitter v0.1 architecture

> Babysitter lets AI agents act autonomously without letting them fail silently.

Babysitter is a **local supervision runtime for AI coding agents**. Models
generate actions; agents coordinate actions; Babysitter makes sure those
actions actually work. It is not an IDE, a model, a gateway, a provider
manager, an MCP marketplace, a memory server, or a cloud platform. If a
proposed feature is really "better routing", "more providers", or "nicer
UI", it is out of scope.

The one rule that governs everything:

> **A model can claim success. Babysitter requires evidence.**

## The lifecycle (the product)

```text
Observe → Validate → Repair → Execute → Verify → Recover → Escalate
```

| Stage | Owner module | Job |
|---|---|---|
| Observe | `store.py`, `server.py`, `loop.py` | Track goal, plan, files, calls, results, failures, retries, state — all in SQLite |
| Validate | `validate.py` | Is this action allowed and well-formed? Tool exists? Args match schema? Paths safe? |
| Repair | `repair.py` | Fix recoverable mistakes (bad JSON, missing/defaultable fields, wrong types) before execution |
| Execute | `execute.py` | Run the validated call (loop mode only; in server mode the external agent executes) |
| Verify | `verify.py` | Did it work? Real test/typecheck subprocesses + real git diff. **Never skipped.** |
| Recover | `recover.py`, `classify.py` | Classify the failure, checkpoint/rollback, retry with failure context |
| Escalate | `escalate.py` | After N consecutive failures on a step, bump that step to a stronger model |

Validate ≠ Verify: validation checks the action is *well-formed* before it
runs; verification checks the result is *correct* after it runs. Most tools
stop at Validate. Verification is why Babysitter exists.

## Integration contract: the frozen schema

The seven stages integrate through **one shared event/task-state schema**
and nothing else — see [`SCHEMA.md`](SCHEMA.md) (frozen v1: 7 stages,
22 event kinds, 5 task statuses, 5 failure classes). `store.py` enforces
it: unknown kinds, wrong stage-for-kind, unknown statuses, oversize
payloads, and terminal-status transitions are all rejected. No stage
reaches into another stage's internals.

## Two modes, one core

**Loop mode** (`loop.py`, exercised by `babysitter demo`) drives the whole
lifecycle itself against the v0.1 minimal toolset (`read_file`,
`write_file`, `edit_file`): ask model → validate → repair → execute →
verify-if-changed → classify → retry-with-context → escalate. This is the
mode that can mark a task `verified_complete`.

**Server mode** (`server.py`, `babysitter start`) is the Layer-1 protocol
adapter: `POST /v1/messages`, `POST /v1/chat/completions`, `GET /v1/models`
(+ `/healthz`). An HTTP proxy cannot see everything inside Cursor/Claude
Code, so server mode honestly supervises only:

1. what passes through the protocol layer — response tool calls are
   validated/repaired against the **agent's own declared schemas**
   before reaching the agent;
2. what the verification engine independently observes — the tree is
   fingerprinted every turn; changes trigger test/typecheck runs, and
   failures are injected as context into the next forwarded turn;
3. tier escalation on consecutive failing turns (tool-error heuristic on
   `role: tool` messages + verification failures).

Babysitter owns model selection in server mode (the requested model id is
accepted; the serving tier decides). Server-mode tasks stay `in_progress`:
completion judgment belongs to the loop in v0.1.

## The completion rule

A task completes **only** when the model stops calling tools **and**
verification passes on the final tree. Model-says-done + tests-fail =
retry. Verification unavailable = loud terminal failure, never silent
success. On terminal failure with unverified changes, the tree is rolled
back to its checkpoint (`rolled_back`); with no changes, `failed`.

**Known v0.1 limitation (documented, not hidden):** Babysitter proves the
tree is in a verified-good state when the agent stops; it does not judge
whether the *goal* was satisfied. Goal judgment needs an LLM judge, which
is explicitly out of v0.1. The trace records the file-change count so
"completed with 0 changes" is visible.

## Checkpoints and rollback

Before a task mutates anything, Recover snapshots the tree: `git-commit`
(a scratch commit; restore = `reset --hard` + `clean -fd` excluding
`.babysitter/`) when the project is a git repo, else `file-copy` (tree
copy + manifest under `.babysitter/checkpoints/`). Every rollback logs
`rollback.done` with the checkpoint id and is inspectable via `trace`.
`.babysitter/` carries its own `.gitignore`, so state never pollutes diffs,
checkpoints, or rollbacks.

## Failure classes and escalation

Classifier (`classify.py`) is total and deterministic (regexes, no model):
`tool-error`, `test-fail`, `syntax-fail`, `no-progress-loop` (same failing
action 3× — takes precedence), `unknown`. The retry context always carries
the class, the attempt count, and the raw truncated evidence.

Escalation rule: **2 consecutive failures on the same step → next ladder
model for that step only** (v0.1 tasks are single-step, so: any 2 in a
row). Any success resets the counter; the stronger model gets a fresh
retry budget. One provider endpoint in v0.1 — ladder entries are model
IDs on that endpoint (e.g. two Ollama models). Top of ladder → loud
`escalation.skipped(no-stronger-model)`, never silent.

## v0.1 scope boundaries (what we do NOT do)

- No shell tool for the model: verification commands come from trusted
  `babysitter.json`, never from model output.
- No path guessing: unrepairable paths fail loudly; protocol mode skips
  path checks entirely (the agent's executor owns them) and says so.
- No streaming (`stream=true` → 400), no token accounting (`usage` zeros,
  documented), no Anthropic image/thinking blocks (400).
- No multi-agent orchestration, Best-of-N/judge, cloud sync, dashboard,
  model benchmarking, or second provider.
- Never, at any stage: browser-cookie scraping or unofficial access.

## Verification-environment gotchas

- **Python `.pyc` staleness:** CPython validates bytecode caches with
  integer-second mtimes, so a same-size edit within the same second can
  re-import stale code and fail verification spuriously. Real agent fixes
  almost always change file size (the demo's does). If you supervise
  Python with sub-second loops, prefer `PYTHONDONTWRITEBYTECODE=1` in
  your verify command. Babysitter runs your command verbatim — it will
  not second-guess your toolchain.
- **Verification commands must be fast and hermetic.** Babysitter runs
  them after every change; a 10-minute suite means 10-minute supervision
  steps. Point `verify.test` at the relevant subset.

## Metrics (from the log, never self-reported)

`metrics.py` computes: repair rate (recovered / malformed), verification
catches, retries, escalations, task success rate, weak-model completions,
and an *approximate* escalations-avoided count (retries − escalations,
labeled as approximate). See `babysitter trace --metrics`.

## Lineage

The JSON-healing catalog and error-informed retry-nudge design descend
from this monorepo's `repairgate` package (which credits Mastra #11078,
json-repair-js, and Instructor); the verify → classify → retry →
checkpoint/rollback supervision loop is original to Babysitter's brief.

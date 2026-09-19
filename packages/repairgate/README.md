# repairgate

> A stateful repair-and-escalation daemon that sits between a coding tool
> and free LLMs, and makes weak models produce competent agentic output.

Point Cursor, Claude Code, or Codex at `repairgate`. Behind it, run the
worst free model you can find. In front of it, the coding tool sees a
competent agent anyway.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design
rationale, the five jobs this package does, why it is explicitly **not**
another multi-provider gateway, and the OSS precedent each piece draws
from.

## The five jobs

1. **Session-aware** — sees the whole task, not one stateless request.
2. **Tool-call repair** — heals broken JSON, fixes missing/wrong-typed
   fields against the tool's schema, and retries with a specific nudge
   when a model forgets to call a tool at all.
3. **Silent escalation** — a step that fails twice in a row is bumped to
   a stronger model, invisibly to the calling tool.
4. **Task-level quota orchestration** — tracks free-tier usage across an
   entire task (surviving an agent firing 25+ calls in a row), not just
   per request.
5. **Dialect normalization** — accepts OpenAI Chat Completions,
   Anthropic Messages, or OpenAI Responses–shaped input and can emit to
   any provider.

Jobs 1–2 are the product. Jobs 3–5 are the plumbing that lets 1–2 plug
into a real coding tool.

## Quick start

From the repo root:

```bash
npm install
npm run build

# Demo mode: a deterministic simulated "dumb model" that emits garbage
# tool calls (markdown-fenced JSON, unquoted keys, trailing commas,
# stringly-typed fields, forgotten tool calls, ...) plus a reliable
# strong model to escalate to. No network access or API key needed.
npm run repairgate -- serve --demo
```

or directly:

```bash
node packages/repairgate/dist/cli.js serve --demo
```

This starts an OpenAI-Chat-Completions-compatible HTTP server on
`http://0.0.0.0:8787/v1/chat/completions` — point your coding tool's
"custom OpenAI-compatible base URL" setting at it. Send an
`x-repairgate-session` header (or an OpenAI `user` field) with a stable
session id so repairgate can track per-step state across the whole task.

## Real free-tier provider

`--demo` is for offline development and the test suite. To point
repairgate at a real OpenAI-compatible free-tier endpoint instead:

```bash
node packages/repairgate/dist/cli.js serve \
  --base-url https://your-free-provider/v1 \
  --api-key "$YOUR_KEY" \
  --model some-free-model
```

See `src/providers/http-backend.ts` for the extension point — it is a
thin `ModelBackend` implementation against any OpenAI-compatible chat
completions endpoint. Building out a ladder of multiple real free
providers (rather than a single rung) is a documented next step, not
required for the core repair/escalation product.

## Package layout

```
src/
  types.ts               Shared types: ToolSpec, RawToolCall, RepairedToolCall,
                          RepairOutcome, ModelTurnRequest/Response, ModelBackend.
  repair/
    json-heal.ts          healJson() — ordered JSON-repair pipeline.
    schema-validate.ts     validateAgainstSchema() + issuesToNudge().
    engine.ts              RepairEngine — repairCall / repairTurn / runStep.
  session/
    session.ts             Session, SessionStore, per-step state + usage.
  escalation/
    controller.ts           EscalationController — silent model-bump on
                             repeated step failure.
  quota/
    orchestrator.ts          QuotaOrchestrator — task-scoped rpm/tpm/spend
                             ledger on top of @test0/core's BudgetManager.
  dialect/
    normalize.ts             OpenAI Chat / Anthropic Messages / OpenAI
                             Responses <-> internal ModelTurnRequest/Response.
  providers/
    dumb-model.ts             DumbModel (scriptable failure modes),
                              ReliableModel (always clean) — deterministic
                              test backends.
    http-backend.ts            HttpModelBackend — real-provider extension
                              point.
  gateway.ts                RepairgateGateway — composes quota + escalation
                             + repair behind one handleStep() call.
  server/daemon.ts            createDaemon() — OpenAI-compatible HTTP server.
  cli.ts                      `repairgate serve` command.
docs/ARCHITECTURE.md          Design rationale + OSS precedent.
test/                         58 vitest tests covering every module above.
```

## Testing

```bash
npm test -w @test0/repairgate
```

All repair, escalation, quota, dialect, and end-to-end gateway behavior
is covered without any network dependency, using the deterministic
`DumbModel`/`ReliableModel` backends.

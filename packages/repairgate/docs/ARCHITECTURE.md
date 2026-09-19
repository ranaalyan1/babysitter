# repairgate — architecture

> A stateful repair-and-escalation daemon that sits between a coding tool
> and free LLMs, and makes weak models produce competent agentic output.

## Positioning

Point Cursor, Claude Code, or Codex at `repairgate` instead of directly at
a model provider. Behind `repairgate` sits the worst free model you can
find. In front of the coding tool, it behaves like a competent agent
anyway.

**This is not another LLM gateway.** Multi-provider routing plumbing
(LiteLLM, Portkey, Bifrost), memory hubs (mem0, Unabyss), and tool/MCP
hubs (Composio, Smithery) are already commodity — every serious gateway
ships a model list, a router, and a dialect translator. Those pieces
exist here too (they have to, to be pluggable into a coding tool at
all), but they are **plumbing, not the product**.

Every one of those gateways is built on an assumption that doesn't hold
for repairgate's target user: they assume you are routing *between good
models*. repairgate assumes the opposite — **the model is dumb and will
emit garbage tool calls**, and its job is to repair and escalate around
that fact, invisibly, so the calling tool never has to know it's talking
to a free/weak backend. That's the one thing nobody has productized, and
it's the entire reason this package exists. If a gateway vendor ships a
"repair mode" checkbox, this is still the right bet, because the
defensibility isn't the checkbox — it's serving people who *only* have
access to free models, end to end, as a first-class use case rather than
an edge case bolted onto a routing product.

## The five jobs

repairgate does exactly five things. Each is implemented as its own
module so it can be tested, understood, and reasoned about independently
— and so the two that matter most ("the product") are not entangled with
the two that are comparatively uninteresting ("the plumbing").

| # | Job | Module | Why it's needed |
|---|-----|--------|------------------|
| 1 | **Session-aware state** | `src/session/session.ts` | Gateways are stateless — one request in, one response out. repairgate sees the whole task: which step is currently failing, how many consecutive failures it's had, which model is currently assigned to it, and cumulative token/request/spend usage. This is the architectural wall between repairgate and a gateway. |
| 2 | **Tool-call repair** | `src/repair/json-heal.ts`, `src/repair/schema-validate.ts`, `src/repair/engine.ts` | Free/weak models routinely emit tool calls wrapped in markdown fences, with unquoted keys, single quotes, trailing commas, stringly-typed numbers/booleans, or missing required fields — or they forget to call a tool at all. repairgate fixes what can be fixed algorithmically, and asks the model to fix the rest with a specific, Instructor-style nudge describing exactly what was wrong. |
| 3 | **Silent escalation** | `src/escalation/controller.ts` | If a model fails on the *same step* twice in a row, that step (only that step — not the whole session) is bumped to the next model on the ladder, without the calling tool ever seeing an error or a model-name change. |
| 4 | **Task-level quota orchestration** | `src/quota/orchestrator.ts` | An agentic coding session can fire 25+ tool calls in a row. Free tiers are rate-limited per-minute and per-day; a naive per-request check doesn't protect a whole task from blowing through a free tier three calls into a 25-call chain. repairgate tracks quota at the task level, and transparently routes around whichever ladder rung is currently exhausted. |
| 5 | **Dialect normalization** | `src/dialect/normalize.ts` | Cursor/Claude Code/Codex don't all speak the same wire format (OpenAI Chat Completions, Anthropic Messages, OpenAI Responses API). repairgate accepts any of the three and can emit to any provider, converging everything on one internal `ModelTurnRequest`/`ModelTurnResponse` shape so jobs 1–4 only have to be implemented once. |

Jobs 1–2 (session state + repair) are **the product** — the part that is
actually hard and actually differentiated. Jobs 3–4 could theoretically
be lifted wholesale from any router (they're "plumbing"), but they still
live here because job 3 (escalation) only works *because* job 1 (session
state) exists, and job 4 (quota) only matters *because* the product is
explicitly aimed at burning through a free tier across a whole task.

## Build order (the order this was actually built in, and why)

1. **Repair engine** (`src/repair/*`) — built first, standalone, fully
   unit-testable with no network and no session/escalation/quota
   scaffolding around it at all. This is deliberately the first thing
   built because it's the core differentiator: if repair doesn't work,
   nothing built on top of it matters.
2. **Escalation logic** (`src/session/session.ts` +
   `src/escalation/controller.ts`) — session state and the fail-counter/
   silent-model-bump behavior, layered directly on top of the repair
   engine from step 1.
3. **Thin gateway shell** (`src/gateway.ts`, `src/dialect/normalize.ts`,
   `src/server/daemon.ts`) — enough dialect translation and HTTP surface
   to plug 1–2 into an actual coding tool as an OpenAI-compatible local
   server.
4. **Quota orchestrator** (`src/quota/orchestrator.ts`) — task-scoped
   free-tier accounting, wired into the gateway shell from step 3.

## Data flow

```
Cursor / Claude Code / Codex
        │  (OpenAI Chat Completions request, any dialect)
        ▼
createDaemon()  (src/server/daemon.ts)
        │  normalize dialect → ModelTurnRequest   (job 5)
        ▼
RepairgateGateway.handleStep()  (src/gateway.ts)
        │
        ├─ QuotaOrchestrator.reserve() / nextAvailableModel()   (job 4)
        │
        ▼
EscalationController.runStep()  (job 3)
        │  reads/writes Session + StepState                     (job 1)
        ▼
RepairEngine.runStep()  (job 2)
        │  healJson → validateAgainstSchema → issuesToNudge → retry
        ▼
ModelBackend.complete()  (DumbModel / ReliableModel / HttpModelBackend)
        │
        ▼
        … response flows back up, denormalized to the caller's dialect,
          escalation transparent, repair transparent, quota transparent.
```

The calling tool only ever sees a clean OpenAI-compatible response. It
never sees a raw JSON parse error, a schema violation, a "model forgot
to call a tool" retry, or a model-name change mid-task.

## OSS precedent

repairgate's design deliberately reuses ideas that are already proven
elsewhere rather than inventing a JSON-repair or cascade-routing
algorithm from scratch:

- **JSON healing catalog** — [Mastra GitHub issue #11078](https://github.com/mastra-ai/mastra/issues/11078)
  proposes `tryRepairJson()`: regex fixes for unquoted keys, single→double
  quotes, trailing-comma removal, and missing commas; it also documents
  the AI SDK's `experimental_repairToolCall` hook. The
  [`json-repair-js`](https://www.npmjs.com/package/json-repair-js) and
  `@toolsycc/json-repair` npm packages corroborate the same fix catalog
  (capitalized/invalid literals like `True`/`None`/`NaN`/`undefined`,
  markdown-fence stripping, prose-around-JSON extraction, unclosed
  brackets). `src/repair/json-heal.ts`'s pipeline is a direct,
  from-scratch TypeScript implementation of this exact catalog.
- **Error-informed retry** — [Instructor](https://python.useinstructor.com/)
  (Python/Pydantic) appends the specific `ValidationError` text to the
  conversation and re-prompts on a schema-validation failure, reportedly
  resolving the majority of validation failures within one or two
  retries. `src/repair/schema-validate.ts`'s `issuesToNudge()` builds the
  same kind of specific, per-field correction message rather than a
  generic "try again" prompt.
- **Cascade / escalate-on-failure routing** — FrugalGPT, AutoMix,
  HybridLLM, and the "Cluster, Route, Escalate" line of work all validate
  the same pattern repairgate uses in `src/escalation/controller.ts`: try
  the cheap/weak model first, and only escalate to a stronger one when a
  concrete quality/validation signal (not a vibe) says the cheap model
  failed.
- **Per-model rpm/tpm/spend accounting** — modeled on
  [LiteLLM](https://docs.litellm.ai/docs/proxy/customer_usage)'s
  proxy-level budget/rate-limit config, reusing `@test0/core`'s
  `BudgetManager` and adding a task-scoped ledger on top
  (`src/quota/orchestrator.ts`) since LiteLLM's own limits are per-model,
  not per-task.

## What's out of scope (on purpose)

- **Generic multi-provider routing** for its own sake (best-price/
  best-latency selection across many *good* models) — that's LiteLLM/
  Portkey/Bifrost's job, not this package's.
- **Memory/long-term context** across unrelated tasks — that's a memory
  hub's job (mem0/Unabyss-style products).
- **Tool/MCP discovery and registry hosting** — that's Composio/
  Smithery's job; repairgate consumes whatever tool schemas the calling
  tool already sends it.

Keeping these out of scope is the whole point: repairgate's bet is that
serving people who *only* have free models — reliably, invisibly — is a
narrower and more defensible product than trying to be a better version
of an already-commoditized gateway.

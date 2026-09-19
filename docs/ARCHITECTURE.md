# test0 V5 Architecture

This document maps the product spec to the actual code in this repo.

## 1–2. Core architecture

```
USER / DEVELOPER
      │
      ▼
Test0Runtime (packages/core/src/runtime.ts)
      │
  ┌───┼────────────┬─────────────┐
  ▼   ▼             ▼             ▼
ModelGateway   SkillRegistry   ToolGateway
(models/)      (skills/)       (tools/)
      │
      ▼
 ModelRouter (router/)
      │
      ▼
 Orchestrator (orchestrator/)
  planner → coder/researcher/reviewer/tester agents
      │
      ▼
 MemoryStore + ContextManager (memory/)
      │
      ▼
 Workspace (.test0/) (workspace/)
```

Every entry point (CLI, MCP server) constructs a single `Test0Runtime`
and drives it identically, so behavior is consistent regardless of which
client is talking to test0.

## 3–5. Model Gateway, Router, Browser access

- `models/gateway.ts` — `ModelGateway` is a provider registry. Nothing
  else imports a concrete provider; new sources register via
  `gateway.registerProvider(new SomeProvider())`.
- `models/providers/*.ts` — example adapters for a free-tier API
  (Gemini, Qwen), a paid API (DeepSeek), and a local runtime (Ollama).
  Each implements the same `ModelProvider` interface
  (`listModels`, `checkAvailability`, `complete`).
- `models/providers/browser-adapter.ts` — the adapter contract for
  browser-based ("free browser access") model use: session handling,
  availability detection, response extraction, rate-limit detection,
  and failure → fallback, exactly per section 5. It does not implement
  real browser automation (that's a computer-use/browser MCP tool
  concern) but plugs into the same `ModelProvider` interface, so the
  router treats it identically to any API provider.
- `router/router.ts` — `ModelRouter` filters models by capability
  (coding/reasoning/vision/tool-use/context/latency), ranks them by the
  active `RoutingPolicy` (`free-first`, `quality-first`, `local-first`,
  `cheapest`, `fastest`), and tries candidates in order with bounded
  per-candidate retries plus automatic fallback on rate-limit/unavailable/
  error, returning one unified `ModelResponse` regardless of which
  provider ultimately served it. Design is directly modeled on two
  production LLM gateways:
  - **LiteLLM's `Router`**: a declarative model list, policy-driven
    ranking, and an ordered fallback chain tried on error/429/timeout.
  - **OpenRouter's provider routing**: deprioritize (don't permanently
    ban) a provider after a recent outage, and weight `cheapest`-policy
    candidates by capability/price² rather than a hard price cliff, so a
    slightly pricier but much better model isn't buried behind the
    single cheapest option.
- `router/health.ts` — `HealthTracker` implements a per-model circuit
  breaker: after `allowedFails` consecutive failures (default 3, matching
  LiteLLM's typical default) a model is skipped for `cooldownMs` (default
  30s, matching OpenRouter's outage-detection window) before being
  retried, rather than either retrying forever or banning it permanently.

## 6. Skill System

- `skills/loader.ts` — `SkillRegistry` implements the open
  [Agent Skills specification](https://agentskills.io/specification)
  (the same `SKILL.md` format used by Claude Code), not a bespoke
  schema: YAML frontmatter (`name`, `description`, `license`,
  `compatibility`, `metadata`, `allowed-tools`) + a Markdown instructions
  body, parsed with a real YAML parser and validated against the spec's
  constraints (name pattern/length, description length, angle-bracket
  injection warning). `skills validate` surfaces every issue.
- Progressive disclosure per the spec: `summaries()` returns the cheap
  Level-1 view (name + description only, ~100 tokens each) for every
  installed skill; `get(name)` returns the full Level-2 body once an
  agent/orchestrator decides a skill is relevant; Level-3
  (`scripts/`/`references/`/`assets/`) is left for the agent to read
  lazily as the body instructs, never eagerly loaded by test0.
- Top-level `skills/` directory ships example skills: python,
  javascript, typescript, react, debugging, code-review, security,
  research, web-research, data-analysis, bioinformatics, and a `custom/`
  slot for user-defined skills — all spec-compliant and portable to any
  other Agent-Skills-compatible runtime.

## 7. Tool Gateway

- `tools/gateway.ts` — `ToolGateway` is a unified discovery/routing
  layer. Every call passes through `PermissionManager` first and is
  recorded to the audit log.
- `tools/builtin/*.ts` — filesystem and terminal tools as first-party
  examples.
- `tools/mcp-client.ts` — `McpServerConnection` connects to any external
  MCP server over stdio and registers each of its tools into the same
  `ToolGateway`, so test0 does not reimplement GitHub/Notion/DB
  integrations — it consumes their MCP servers directly.

## 8–9. Orchestrator and Planning

- `orchestrator/planner.ts` — `TaskPlanner.plan(goal)` turns a free-form
  goal into a dependency-ordered `ExecutionPlan` with a dynamic step
  count (not a fixed template): understand → [research] → design →
  [implement] → [test → fix] → [github] → [security review] → review →
  [docs] → final report.
- `orchestrator/agents.ts` — `DEFAULT_AGENTS` defines planner, coder,
  researcher, reviewer, and tester agents using CrewAI's role/goal/
  backstory shape (role = what the agent does, goal = what it optimizes
  for, backstory = persona/expertise framing), plus test0's own
  skills/tools/preferred-task-type declarations that CrewAI doesn't need
  (it doesn't have a skill system or a model router).
- `orchestrator/orchestrator.ts` — `Orchestrator.run(goal)` executes the
  plan respecting dependencies, assembling context per step via
  `ContextManager`, routing each step's model call via `ModelRouter`, and
  producing a final markdown report plus structured `StepResult[]`.
  Independent, dependency-satisfied steps run concurrently (bounded by
  `maxConcurrency`, configurable in `test0.config.yaml`) rather than
  strictly serializing every step, since two unrelated branches of a plan
  (e.g. two research steps) have no reason to wait on each other.

## 10–11. Memory and Context

- `memory/store.ts` — `MemoryStore` is a file-backed store over the six
  memory types (user/project/agent/task/conversation/tool-state) with
  `remember`/`recall`/`forget`, so persistence can later be swapped for
  a real DB/vector store without touching callers.
- `memory/context.ts` — `ContextManager.assemble(...)` combines task +
  retrieved memory + skills + tool results + previous agent results +
  recent conversation into a single message list under a character
  budget, retrieving selectively rather than dumping full history.

## 12–13. Computer/Browser use and Autonomous workflows

Computer-use and scheduled/autonomous workflows are designed as tools
and orchestrator goals respectively, not special-cased subsystems:
a browser-control MCP server plugs into `ToolGateway` like any other
tool, and a "monitor GitHub issues every morning" workflow is just a
recurring call to `Orchestrator.run(...)` (e.g. from a cron job or a
scheduler process), reusing the same planning/execution/memory path as
an interactive request.

## 14. Permissions and Security

- `security/permissions.ts` — `PermissionManager` resolves
  allow/ask/block decisions by longest dotted-scope-prefix match
  (`filesystem.delete` > `filesystem.*` > `*`), defaults unknown scopes
  to `ask`, records every check to an audit log, and exposes
  `resolveApproval` for turning a pending "ask" into a durable rule.
- `DEFAULT_PERMISSION_RULES` mirrors the example table in the spec
  (filesystem read/write allow, delete ask; GitHub read allow, create/
  merge PR ask; browser navigate/download allow, purchase block).

## 15–16. Benchmarking and Cost/Availability policy

- `benchmark/store.ts` — `BenchmarkStore.runSuite(modelId, cases)` runs
  reproducible test cases against a model and stores pass/fail, latency,
  and cost; `getScore()` is consulted by the router as one ranking input
  (30% weight) alongside raw capability scores (70%), never as a
  subjective override.
- Routing policies (`RoutingPolicy`) implement the free-first,
  quality-first, and local-first orderings described in section 16
  directly as comparator chains in `router/router.ts`, plus `cheapest`
  and `fastest` as additional user-selectable policies.

## Observability (tracing) and Budgets/Rate limits

- `observability/tracer.ts` — `Tracer`, modeled on how
  [Langfuse](https://langfuse.com) (an OTel-native LLM observability
  platform) and OpenTelemetry structure traces: a `Trace` is one
  end-to-end unit of work (an orchestration `run()`), containing nested
  `Span`s — one `agent`-kind span per orchestrator step, one
  `model`-kind span per model call inside it — each carrying
  start/end time, status, token/cost usage, and attributes. Traces are
  kept in memory during a process and, when `tracingEnabled` is on,
  appended as JSONL to `.test0/traces/traces.jsonl` (one line per
  completed trace), deliberately as plain JSON rather than requiring a
  running collector. `toOtlpLikeJson()` renders a trace as an
  OpenTelemetry-shaped span list so it can be forwarded to a real OTel
  collector or Langfuse's OTel endpoint later without test0 depending on
  the OTel SDK. `Tracer.usageSummary()` aggregates cost/latency/error
  counts per model across persisted traces, mirroring LiteLLM's
  spend-logs table.
- `budget/limiter.ts` — `BudgetManager`, modeled on
  [LiteLLM's](https://docs.litellm.ai/docs/proxy/customer_usage)
  per-deployment `rpm`/`tpm` limits and per-key/team spend budgets:
  enforces independent **rpm** (sliding 60s request-count window),
  **tpm** (sliding 60s token-count window — tracked separately from rpm
  because a single agentic call can carry many thousands of tokens),
  and **maxBudgetUsd** (lifetime spend cap) per model id, with `"*"` as
  a wildcard default. `canProceed()` is a pre-call check the router
  consults inside `selectCandidates()` to skip any model already at its
  limit (LiteLLM's `optional_pre_call_checks` shape); `record()` is a
  post-call accounting hook fed the actual token/cost usage returned by
  the provider.
- Both are wired end to end: `Test0Runtime` builds one `Tracer` and one
  `BudgetManager` per workspace (limits loaded from `test0.config.yaml`'s
  `budgets` section) and injects them into both `ModelRouter` and
  `Orchestrator`; `Orchestrator.run()` starts a root trace and returns
  its id as `OrchestrationResult.traceId`.

## Response cache and Guardrails

- `cache/response-cache.ts` — `ResponseCache`, modeled on
  [GPTCache](https://github.com/zilliztech/GPTCache)'s two-tier design:
  an **exact tier** (hash of model id + normalized prompt → O(1) lookup,
  always correct) and a **semantic tier** (nearest-neighbor search
  against a similarity threshold, so a paraphrased near-duplicate prompt
  still hits). GPTCache itself uses real embeddings + a vector store;
  test0 stays dependency-free and fully offline by approximating
  semantic similarity with Jaccard similarity over normalized tokens
  behind the exact same interface — swap `similarity()` for a real
  embedding backend to get GPTCache's actual recall/precision without
  touching any caller. Entries carry a TTL and are evicted
  least-recently-used past `maxEntries`, and `stats()` reports
  exact/semantic hit rate the same way GPTCache's own dashboards do, so
  a threshold that's too loose (correctness risk) or too tight (no
  savings) is visible rather than silently wrong. The router checks the
  cache against its top-ranked candidate before making any real call,
  and populates it on every successful completion.
- `guardrails/guardrails.ts` — `GuardrailEngine`, modeled on
  [Guardrails AI](https://github.com/guardrails-ai/guardrails)'s
  validator-pipeline design and [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails)'
  input/output "rails" split. Each `Validator` is a small, independent
  check (Guardrails AI hub validator shape: `name` + `check(text)`), so
  the router runs:
  - an **input rail** on the outbound prompt — heuristic
    prompt-injection/jailbreak detection ("ignore previous
    instructions", role-override attempts) — and **blocks** the call
    entirely on a match, the same class of check as NeMo's
    `check_input_safety` execution rail;
  - an **output rail** on the model's response — PII detection +
    redaction (email/phone/SSN/credit-card, Guardrails AI's
    `DetectPII`/`ValidPII` validators) and secret/credential leakage
    (API-key-shaped tokens) — and **redacts** matches in place rather
    than blocking, following Guardrails AI's `OnFailAction.FIX` default
    so a paid-for completion isn't thrown away over one flagged token.
  Both rails are regex/heuristic-based to stay dependency-free and
  offline-runnable; swap in a real classifier or moderation API behind
  the same `Validator` interface for production-grade recall.
- Both are wired into `ModelRouter`: `route()` runs the input rail
  before selecting candidates and consults the cache right after, and
  `tryCandidateWithRetries()` runs the output rail on every successful
  response, attaching any findings to `ModelResponse.guardrailFindings`.

## 17. CLI

`packages/cli` implements `test0 init|connect|models|skills|tools|
agents|memory|run|config|traces|safety|cache` using Commander, all
operating on the same `Test0Runtime`. `test0 traces [list]` lists
recorded traces, `test0 traces show <id>` prints every span in one, and
`test0 traces usage` prints the LiteLLM-style per-model spend/latency/
error summary plus live rpm/tpm/spend budget state for the current
process. `test0 safety check "<text>"` runs text through both
guardrail rails and shows any redaction. `test0 cache stats`/`test0
cache clear` inspect and reset the in-process response cache.

## 18. MCP Interface

`packages/mcp-server` exposes `ask_model`, `route_task`, `use_skill`,
`use_tool`, `delegate_task`, `search_memory`, `save_memory`, and
`run_agent` as MCP tools over stdio, so Claude Code/Cursor/Codex/any
MCP client gets test0's full capability surface through one server
without needing to understand its internals.

## Declarative configuration

- `config/schema.ts` / `config/loader.ts` — an optional, git-committed
  `test0.config.yaml` at the project root, modeled directly on LiteLLM's
  `proxy_config.yaml` (`model_list` + `router_settings`) and the
  `mcpServers` map used by Claude Desktop/Cursor/Claude Code config
  files. It layers on top of `.test0/config.json` (which remains the
  mutable runtime state written by commands like `test0 config
  permission ...`): defaults → `test0.config.yaml` → `.test0/config.json`
  overrides. `test0 init --with-config` scaffolds a commented example.
  Loading an older `.test0/config.json` (missing newer fields, e.g. from
  before `router`/`orchestrator` settings existed) is backfilled with
  current defaults rather than crashing, so upgrading test0 never breaks
  an existing workspace.

## 19. Workspace

- `workspace/workspace.ts` — `Workspace.init/open` manages a project's
  `.test0/` directory: `config.json` (routing policy, permission rules,
  enabled skills/providers, configured MCP servers, per-model budgets,
  tracing on/off), `memory.json`, `task-history.json`, an `artifacts/`
  directory, and a `traces/` directory holding `traces.jsonl`.

## What's simulated vs. real

To keep test0 fully runnable in any environment without API keys or
network access, the shipped model providers (`gemini.ts`, `deepseek.ts`,
`qwen.ts`, `local-ollama.ts`) produce deterministic simulated
completions with realistic latency/token/cost accounting, and expose
`setFailureMode()` so the router's fallback logic is exercised and
testable. Everything else — routing, planning, orchestration, memory,
permissions, tool gateway, MCP server — is real, working logic. To go to
production, replace `simulateCompletion` in each provider with an actual
HTTP call (or, for `BrowserModelProvider`, a real `BrowserSessionAdapter`
backed by a computer-use/browser MCP tool).

The response cache's semantic tier is likewise a documented
approximation: it uses Jaccard token-overlap instead of real embeddings
so it needs no vector store or API key. `ResponseCache`'s public
interface (`get`/`set`/`stats`) is the same shape GPTCache exposes, so
swapping in a real embedding model + vector index is a drop-in change,
not a redesign. The guardrail validators are regex/heuristic-based for
the same offline-first reason — swap in a moderation API or fine-tuned
classifier behind the `Validator` interface for production-grade recall
on prompt-injection/toxicity detection.

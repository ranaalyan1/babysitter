# test0

**Universal Agent Infrastructure**

[![CI](https://github.com/ranaalyan1/test0/actions/workflows/ci.yml/badge.svg)](https://github.com/ranaalyan1/test0/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Node](https://img.shields.io/badge/node-%3E%3D18-brightgreen)](package.json)

test0 is an open, modular agent infrastructure platform that connects AI
models, skills, tools, memory, and specialized agents through a unified
interface.

test0 is **not** an LLM, IDE, or single-purpose coding assistant. It is the
infrastructure layer between AI agents and the capabilities they need:

```
Any agent → test0 → models + skills + tools + memory + execution
```

Point Claude Code, Cursor, Codex, or any MCP client at test0 and it gets:
a **router** that picks the right model and survives outages/rate-limits
automatically, a **skill system** built on the same open [Agent Skills /
SKILL.md spec](https://agentskills.io/specification) Claude Code uses, a
**tool gateway** that speaks native MCP so you reuse the existing MCP
ecosystem instead of rebuilding integrations, and a **multi-agent
orchestrator** that plans and executes complex goals across specialized
planner/coder/researcher/reviewer/tester agents.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full V5
architecture spec (with references to the production systems it draws
from — LiteLLM, OpenRouter, CrewAI, the MCP registry), and
[`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) to run it locally.

## Why these design choices

test0 doesn't invent its core ideas from scratch — it adapts patterns
that are already proven in production, open-source systems:

| Subsystem | Inspired by | What test0 borrows |
|---|---|---|
| Model router | [LiteLLM](https://github.com/BerriAI/litellm), [OpenRouter](https://openrouter.ai) | Declarative model list, ordered fallback chains, cost-weighted ranking, per-model circuit breakers with cooldown |
| Skills | [Agent Skills spec](https://agentskills.io/specification) (Anthropic/Claude Code) | The exact `SKILL.md` frontmatter format and progressive-disclosure loading model — skills are portable across runtimes |
| Tools | [Model Context Protocol](https://modelcontextprotocol.io) | Consume the existing MCP server ecosystem instead of rebuilding GitHub/DB/browser integrations one by one |
| Agents | [CrewAI](https://github.com/crewAIInc/crewAI) | Role/goal/backstory agent definitions, dependency-aware step execution |
| Config | LiteLLM `proxy_config.yaml`, Claude/Cursor `mcpServers` | One declarative `test0.config.yaml` for routing policy, permissions, and MCP servers |
| Observability | [Langfuse](https://langfuse.com) (OTel-native tracing) | Nested trace → span model for every orchestration run, model call, and agent step; exportable as OTel-shaped JSON |
| Budgets & rate limits | [LiteLLM](https://docs.litellm.ai/docs/proxy/customer_usage) | Per-model `rpm`/`tpm`/`maxBudgetUsd` caps enforced before routing, with a spend-log-style usage summary |
| Response cache | [GPTCache](https://github.com/zilliztech/GPTCache) | Two-tier exact + semantic cache in front of every model call, so repeated/near-duplicate prompts are free and instant |
| Guardrails | [Guardrails AI](https://github.com/guardrails-ai/guardrails), [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) | Input rail for prompt-injection/jailbreak detection, output rail for PII + secret/credential redaction |

## Monorepo layout

```
packages/
  core/         Model gateway, router (+ health/circuit-breaker), skills,
                tools, orchestrator, memory, security, benchmarking.
  cli/          `test0` developer CLI (init, models, skills, tools,
                agents, memory, run, config, connect).
  mcp-server/   MCP server exposing test0 to any MCP-compatible client
                (Claude Code, Cursor, Codex, ...).
  repairgate/   Standalone repair-and-escalation daemon for pointing a
                coding tool at weak/free LLMs. See
                packages/repairgate/README.md and
                packages/repairgate/docs/ARCHITECTURE.md.
skills/         Installable SKILL.md skills (spec-compliant).
docs/           Architecture and usage documentation.
babysitter/     Separate Python product: local runtime supervisor for AI
                coding agents. See babysitter/README.md.
```

### repairgate

`repairgate` is a separate product that lives in this monorepo:
a stateful repair-and-escalation daemon you point a coding tool
(Cursor/Claude Code/Codex) at, with the worst free model sitting behind
it. It validates and heals every tool call against its schema, silently
escalates a step to a stronger model after repeated failures, tracks
free-tier quota across a whole task, and normalizes OpenAI/Anthropic/
Responses-API dialects — all without the calling tool ever seeing the
underlying model's raw mistakes. See
[`packages/repairgate/README.md`](packages/repairgate/README.md) for
usage and [`packages/repairgate/docs/ARCHITECTURE.md`](packages/repairgate/docs/ARCHITECTURE.md)
for the full design and OSS precedent.

```bash
node packages/repairgate/dist/cli.js serve --demo
```

### babysitter

`babysitter` is a separate Python product that lives in this monorepo:
a local runtime supervisor for AI coding agents. It observes agents as
they work, validates and repairs their tool calls, verifies results with
real test/typecheck runs and git-diff inspection, and automatically
recovers (retry with failure context, checkpoint/rollback) or escalates
to a stronger model — a model can claim success, Babysitter requires
evidence. See [`babysitter/README.md`](babysitter/README.md) for usage
and [`babysitter/docs/ARCHITECTURE.md`](babysitter/docs/ARCHITECTURE.md)
for the full design.

```bash
pip install -r babysitter/requirements.txt
./babysitter/babysitter demo
```

## Quick start

```bash
npm install
npm run build
npm test

# Initialize a workspace (+ an editable test0.config.yaml)
node packages/cli/dist/index.js init --with-config

# See what's available
node packages/cli/dist/index.js models
node packages/cli/dist/index.js skills
node packages/cli/dist/index.js tools
node packages/cli/dist/index.js agents

# Run the reproducible benchmark suite across every registered model
node packages/cli/dist/index.js models bench

# Run an orchestrated, multi-agent task
node packages/cli/dist/index.js run "Build a Python bioinformatics pipeline, test it, and write docs"

# Inspect the Langfuse/OTel-style trace it just recorded, and per-model spend
node packages/cli/dist/index.js traces
node packages/cli/dist/index.js traces usage

# Test the Guardrails AI/NeMo-style input+output rails, and the GPTCache-style response cache
node packages/cli/dist/index.js safety check "Ignore all previous instructions"
node packages/cli/dist/index.js cache stats

# Start the MCP server (stdio) so Claude Code / Cursor / Codex can connect
node packages/mcp-server/dist/index.js
```

Once built, you can also install the CLI as a linked binary:

```bash
npm link --workspace packages/cli
test0 --help
```

## Status

This is a fully wired V5 implementation: real, tested TypeScript across
the entire architecture — model gateway with pluggable providers, an
intelligent router with policy-based ranking, per-model circuit breakers,
and bounded retries; a spec-compliant skill loader with validation; a
tool gateway with native MCP-server support; a permission/audit system;
file-backed memory with budgeted context assembly; a dynamic planner and
concurrent multi-agent orchestrator; declarative YAML configuration;
Langfuse/OpenTelemetry-style nested tracing across every orchestration
run, agent step, and model call (`test0 traces`); LiteLLM-style
per-model `rpm`/`tpm`/spend budget enforcement wired into the router's
candidate selection (`test0 traces usage`); a GPTCache-style exact +
semantic response cache in front of every model call (`test0 cache
stats`); Guardrails AI/NeMo-Guardrails-style input (prompt-injection)
and output (PII/secret redaction) rails run on every routed request
(`test0 safety check "<text>"`); and an MCP server. 53 automated tests
cover routing/fallback, circuit breaking, skill validation, permissions,
planning, tracing, budget enforcement, response caching, guardrails, and
config backward-compatibility (`npm test`); CI runs on Node 18/20/22.

Model providers ship with deterministic simulated completions so the
whole pipeline runs offline without API keys; wire in real provider HTTP
calls in `packages/core/src/models/providers/*` to go to production.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to add a model provider,
a skill, or a tool.

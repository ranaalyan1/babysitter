# Getting Started

## Prerequisites

- Node.js >= 18

## Install & build

```bash
npm install
npm run build
```

This builds three workspace packages in order: `@test0/core`,
`@test0/cli`, `@test0/mcp-server`.

## Initialize a workspace

Run this inside whatever project you want test0 to manage:

```bash
node /path/to/test0/packages/cli/dist/index.js init
```

This creates a `.test0/` directory with `config.json`, `memory.json`,
`task-history.json`, and an `artifacts/` folder (see
[Workspace](ARCHITECTURE.md#19-workspace)).

If you `npm link --workspace packages/cli`, you can just run `test0 init`.

## Explore the CLI

```bash
test0 models                          # list models + health status + current routing policy
test0 models set-policy free-first    # free-first | quality-first | local-first | cheapest | fastest
test0 models bench [modelId]          # run the reproducible benchmark suite
test0 skills                          # list installed skills
test0 skills show python              # print a skill's instructions (Level 2 disclosure)
test0 skills validate                 # validate every skill against the Agent Skills spec
test0 tools                           # list tools + permission status
test0 tools call filesystem.read --args '{"path":"README.md"}'
test0 agents                          # list specialized agents (role/goal/backstory)
test0 memory                          # inspect stored memory
test0 memory search "bug"             # search memory
test0 config                          # view merged workspace config
test0 config permission terminal.execute allow   # change a permission rule
test0 connect                         # check provider + MCP server connectivity
test0 run "Build a Python bioinformatics pipeline, test it, and write docs"
test0 traces                          # list recorded orchestration traces
test0 traces show <traceId>           # inspect every span in one trace
test0 traces usage                    # per-model spend/latency/errors + live rpm/tpm budget state
test0 safety check "<text>"           # test the input (prompt-injection) and output (PII/secret) rails
test0 cache stats                     # exact/semantic response-cache hit rate for this process
test0 cache clear                     # clear the in-process response cache
```

## Declarative configuration

Run `test0 init --with-config` to also scaffold an editable
`test0.config.yaml` at the project root — commit this to git. It lets you
set the routing policy, retry/circuit-breaker knobs, enabled providers,
permission overrides, and MCP servers declaratively instead of only via
CLI mutations:

```yaml
router:
  policy: quality-first
  retriesPerCandidate: 1
  health:
    allowedFails: 3
    cooldownMs: 30000

permissions:
  terminal.execute: allow

mcpServers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"

# LiteLLM-style per-model rpm/tpm/spend caps, enforced before routing.
# "*" applies to every model; a specific model id overrides it.
budgets:
  "*":
    rpm: 60
    tpm: 100000
  deepseek-r1:
    maxBudgetUsd: 5.00

# Record a Langfuse/OpenTelemetry-shaped trace (nested spans per agent
# step and model call) to .test0/traces/traces.jsonl on every `run`.
tracingEnabled: true

# GPTCache-style exact + semantic response cache in front of the model
# gateway. similarityThreshold is a similarity score in [0, 1]; GPTCache's
# own docs cite ~0.85 as a reasonable starting point.
cache:
  enabled: true
  ttlMs: 300000
  similarityThreshold: 0.85

# Guardrails AI/NeMo-Guardrails-style input (prompt-injection/jailbreak)
# and output (PII + secret/credential redaction) checks.
guardrails:
  enabled: true
```

`.test0/config.json` remains the mutable runtime state; `test0.config.yaml`
is layered on top of it every time the workspace loads.

A model that hits its `rpm`/`tpm`/`maxBudgetUsd` cap is transparently
excluded from routing (like any other unhealthy candidate) until its
sliding 60s window clears, so a misbehaving loop degrades to a fallback
model instead of blowing through a real provider's rate limit.

`test0 run` is the full orchestration path: it plans dynamic steps,
assigns specialized agents (planner/coder/researcher/reviewer/tester),
routes each step's model call through the intelligent router (with
automatic fallback), and prints a final report.

## Connect an MCP client (Claude Code, Cursor, Codex, ...)

Point your MCP-compatible client at:

```json
{
  "mcpServers": {
    "test0": {
      "command": "node",
      "args": ["/path/to/test0/packages/mcp-server/dist/index.js"],
      "env": { "TEST0_PROJECT_DIR": "/path/to/your/project" }
    }
  }
}
```

The server exposes: `ask_model`, `route_task`, `use_skill`, `use_tool`,
`delegate_task`, `search_memory`, `save_memory`, `run_agent`.

## Add your own model provider

Implement the `ModelProvider` interface (`packages/core/src/types/index.ts`)
— `listModels`, `checkAvailability`, `complete` — then register it:

```ts
import { Test0Runtime } from "@test0/core";
// runtime.gateway.registerProvider(new MyProvider());
```

Nothing else in test0 needs to change; the router and orchestrator work
with any registered provider automatically.

## Add your own skill

Create `skills/my-skill/SKILL.md`:

```markdown
---
name: my-skill
version: 1.0.0
description: What this skill teaches an agent to do
tags: [example]
---
# My Skill

Instructions go here.
```

Restart the runtime (or call `runtime.skills.loadAll()`) to pick it up.

## Connect an external MCP server as a tool source

```ts
import { McpServerConnection } from "@test0/core";

const conn = new McpServerConnection({ id: "github", command: "npx", args: ["-y", "@modelcontextprotocol/server-github"] });
await conn.connect(runtime.tools);
```

Every tool the external server exposes becomes callable through
`runtime.tools.call("github.<toolName>", args)`, subject to the same
permission checks as builtin tools.

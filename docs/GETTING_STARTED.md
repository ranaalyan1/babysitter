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
test0 models              # list models + current routing policy
test0 models set-policy free-first   # free-first | quality-first | local-first | cheapest | fastest
test0 skills               # list installed skills
test0 skills show python   # print a skill's instructions
test0 tools                # list tools + permission status
test0 tools call filesystem.read --args '{"path":"README.md"}'
test0 agents                # list specialized agents
test0 memory                # inspect stored memory
test0 memory search "bug"   # search memory
test0 config                 # view workspace config
test0 config permission terminal.execute allow   # change a permission rule
test0 connect                # check provider connectivity
test0 run "Build a Python bioinformatics pipeline, test it, and write docs"
```

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

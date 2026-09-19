# test0

**Universal Agent Infrastructure**

test0 is an open, modular agent infrastructure platform that connects AI
models, skills, tools, memory, and specialized agents through a unified
interface.

test0 is **not** an LLM, IDE, or single-purpose coding assistant. It is the
infrastructure layer between AI agents and the capabilities they need:

```
Any agent → test0 → models + skills + tools + memory + execution
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full V5
architecture spec, and [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)
to run it locally.

## Monorepo layout

```
packages/
  core/         Model gateway, router, skills, tools, orchestrator,
                memory, security, benchmarking — the engine.
  cli/          `test0` developer CLI (init, models, skills, tools,
                agents, memory, run, config, connect).
  mcp-server/   MCP server exposing test0 to any MCP-compatible client
                (Claude Code, Cursor, Codex, ...).
skills/         Installable SKILL.md-style skill definitions.
docs/           Architecture and usage documentation.
```

## Quick start

```bash
npm install
npm run build

# Initialize a workspace in the current project
node packages/cli/dist/index.js init

# See what's available
node packages/cli/dist/index.js models
node packages/cli/dist/index.js skills
node packages/cli/dist/index.js tools
node packages/cli/dist/index.js agents

# Run an orchestrated, multi-agent task
node packages/cli/dist/index.js run "Build a Python bioinformatics pipeline, test it, and write docs"

# Start the MCP server (stdio) so Claude Code / Cursor / Codex can connect
node packages/mcp-server/dist/index.js
```

Once built, you can also install the CLI as a linked binary:

```bash
npm link --workspace packages/cli
test0 --help
```

## Status

This is the V5 scaffold: real, runnable TypeScript across the full
architecture (model gateway with pluggable providers, an intelligent
router with policy-based fallback, a skill loader, a tool gateway with
MCP-server support, a permission/audit system, file-backed memory with
context assembly, a planner + multi-agent orchestrator, workspaces, and
an MCP server). Model providers ship with deterministic simulated
completions so the whole pipeline runs offline; wire in real provider
API calls in `packages/core/src/models/providers/*` to go to production.

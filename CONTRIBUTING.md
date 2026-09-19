# Contributing to test0

test0 is infrastructure, not a single app — most contributions fall into
one of these buckets:

- **A new model provider** (`packages/core/src/models/providers/`)
- **A new skill** (`skills/<name>/SKILL.md`)
- **A new builtin tool, or an MCP server integration**
- **Improvements to the router, orchestrator, memory, or permission system**
- **CLI or MCP-server ergonomics**

## Development setup

```bash
npm install
npm run build
npm test
```

Each package builds independently (`npm run build -w @test0/core`, etc.)
but `@test0/cli` and `@test0/mcp-server` depend on `@test0/core`'s
compiled output, so build core first — `npm run build` at the root
already does this in the right order.

## Adding a model provider

1. Implement the `ModelProvider` interface in a new file under
   `packages/core/src/models/providers/`. Look at `gemini.ts` for the
   shortest example, or `browser-adapter.ts` for the browser-access
   contract described in the architecture doc.
2. Export it from `packages/core/src/index.ts`.
3. Register it in `packages/core/src/runtime.ts`'s `ALL_BUILTIN_PROVIDERS`
   map if it should ship enabled by default, or leave it for consumers to
   register themselves via `runtime.gateway.registerProvider(...)`.
4. Add a test in `packages/core/test/` exercising at least one success
   and one failure path (see `router.test.ts` for the pattern).

## Adding a skill

Skills follow the open [Agent Skills specification](https://agentskills.io/specification)
(the same SKILL.md format used by Claude Code). Run:

```bash
test0 skills validate
```

after adding a skill to check it against the spec (name format,
description length, etc.) before opening a PR.

## Adding a tool

- Builtin tools live in `packages/core/src/tools/builtin/` and implement
  `ToolExecutor`.
- External integrations should be exposed as an MCP server and connected
  via `mcpServers:` in `test0.config.yaml` rather than reimplemented as a
  builtin — see `docs/GETTING_STARTED.md`.

Every tool must declare a `permissionKey`; if it performs a
destructive or high-impact action, its default permission rule (in
`DEFAULT_PERMISSION_RULES`) should be `ask` or `block`, not `allow`.

## Tests

We use [Vitest](https://vitest.dev). Add tests next to the subsystem you
touched under `packages/core/test/`. CI runs `npm run build && npm test`
on Node 18/20/22.

## Code style

- TypeScript strict mode; avoid `any`.
- Keep provider/vendor-specific logic behind the `ModelProvider` /
  `ToolExecutor` interfaces — nothing in `router/`, `orchestrator/`, or
  `memory/` should import a concrete provider or tool.

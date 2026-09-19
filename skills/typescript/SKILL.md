---
name: typescript
description: TypeScript conventions for strict, well-typed code. Use when writing or reviewing .ts/.tsx files or configuring a TypeScript project.
license: MIT
allowed-tools: filesystem.read filesystem.write terminal.run
metadata:
  category: coding
  test0.tags: coding,typescript
---
# TypeScript Skill

## When to use this skill
Writing, editing, or reviewing TypeScript source, or setting up/adjusting
`tsconfig.json`.

## Instructions
1. Enable `strict: true` in `tsconfig.json` for new projects.
2. Avoid `any`; prefer `unknown` with narrowing, or generics.
3. Model domain data with discriminated unions instead of optional-field
   soup.
4. Co-locate types near their usage unless they are shared across
   packages/modules, in which case put them in a dedicated `types/` module.
5. Prefer `interface` for extendable object shapes, `type` for unions
   and mapped types.

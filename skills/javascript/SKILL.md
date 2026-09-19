---
name: javascript
description: Modern JavaScript (ES2022+) conventions for Node.js and browser code. Use when writing or reviewing JavaScript files or npm-based projects.
license: MIT
allowed-tools: filesystem.read filesystem.write terminal.run
metadata:
  category: coding
  test0.tags: coding,javascript
---
# JavaScript Skill

## When to use this skill
Writing, editing, or reviewing `.js`/`.mjs`/`.cjs` files, or an npm-based
project without TypeScript.

## Instructions
1. Use ES2022+ syntax and ESM (`import`/`export`); avoid CommonJS in new code.
2. Never use `var`; prefer `const`, fall back to `let` only when reassigned.
3. Use `async`/`await` over raw `.then()` chains for readability.
4. Lint with ESLint and format with Prettier; respect an existing config
   over introducing a new one.
5. Avoid implicit globals — always declare variables.

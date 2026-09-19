---
name: typescript
version: 1.0.0
description: TypeScript conventions for strict, well-typed code
tags: [coding, typescript]
requiredTools: [filesystem.read, filesystem.write, terminal.run]
---
# TypeScript Skill

- Enable `strict` mode in tsconfig.
- Avoid `any`; prefer `unknown` + narrowing or generics.
- Model domain data with discriminated unions where useful.
- Co-locate types near usage unless shared across packages.

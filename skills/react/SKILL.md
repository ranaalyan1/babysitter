---
name: react
description: React application conventions for components, state, and structure. Use when building or reviewing React/JSX/TSX UI code.
license: MIT
allowed-tools: filesystem.read filesystem.write terminal.run
metadata:
  category: coding
  test0.tags: coding,react,frontend
---
# React Skill

## When to use this skill
Building or reviewing React components, hooks, or application structure.

## Instructions
1. Use function components with hooks; do not introduce class components
   in new code.
2. Keep state as local as possible; lift state only when multiple
   components genuinely need to share it.
3. Co-locate a component with its styles and tests.
4. Prefer composition (children, render props) over deep prop-drilling;
   reach for context or a state library only when prop-drilling becomes
   painful across 3+ levels.
5. Memoize (`useMemo`/`useCallback`) only after observing a real
   performance issue, not preemptively.

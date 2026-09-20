# Changelog

## 0.4.0 — Local console & visual identity

- Original watchful-bracket logo, wordmarks, repository cover and brand guide.
- Packaged responsive console: overview, task search/filtering, timelines,
  verification evidence, checkpoint/file inspection, integrations and preferences.
- Separate read-only SQLite/API boundary; explicit demo fixtures, local-token
  protection for real non-loopback access, bounded previews and no execution routes.
- Offline documentation, keyboard navigation, trace export and self-hosted font.
- Rewritten README, contribution/security guidance, backend and browser regressions.
- Core schema and native supervision contracts are unchanged.

## 0.3.0 — Codex & OpenCode

- Codex native hooks with guarded patch paths, no approval override, and bounded
  recovery retaining the same task/checkpoint/budget.
- OpenCode owned JSONL CLI supervision and same-session recovery.
- Shared native lifecycle preserves Claude compatibility; additive Codex tables.
- 190 passing tests including all official native clients, plus controlled
  ItsDangerous/Click upstream-suite validation. Scripted endpoints, not real models.

## 0.2.0 — Claude Code

- Reversible project-local native hook integration, independent Stop verification,
  inspectable failed changes, bounded recovery and native permissions preserved.
- 119 tests including actual Claude CLI recovery against a local scripted endpoint.

## 0.1.0 — Runtime foundation

- Observe → Validate → Repair → Execute → Verify → Recover → Escalate.
- Frozen v1 task/event schema, local SQLite, protocol adapters, deterministic
  verification, checkpoints, recovery, CLI, metrics and regression fixes.

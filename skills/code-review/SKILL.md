---
name: code-review
description: Checklist and standards for reviewing code changes for correctness, quality, and consistency. Use when acting as a reviewer agent or asked to review a diff/PR.
license: MIT
metadata:
  category: quality
  test0.tags: review,quality
---
# Code Review Skill

## When to use this skill
Reviewing a diff, pull request, or freshly generated implementation.

## Instructions
Check for, in order of importance:
1. **Correctness** — does it actually do what it claims, including edge cases?
2. **Error handling** — are failures surfaced, not swallowed?
3. **Security** — see the `security` skill for a dedicated checklist.
4. **Test coverage** — are the changed code paths exercised by tests?
5. **Naming and clarity** — would a new contributor understand this in six months?
6. **Consistency** — does it match existing project conventions rather than
   introducing a new pattern gratuitously?

Prefer specific, actionable comments ("this will throw if `items` is
empty — add a guard") over vague feedback ("this could be cleaner").

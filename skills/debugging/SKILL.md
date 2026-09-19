---
name: debugging
description: Systematic methodology for diagnosing and fixing bugs. Use whenever a test fails, an error is reported, or behavior doesn't match expectations.
license: MIT
metadata:
  category: quality
  test0.tags: debugging,testing
---
# Debugging Skill

## When to use this skill
Any time something is broken: a failing test, an exception, or output
that doesn't match expectations.

## Instructions
1. Reproduce the failure reliably before attempting any fix.
2. Bisect: find the smallest input or change that triggers the bug.
3. Read the full error message and stack trace before forming a
   hypothesis — do not guess from the symptom alone.
4. Add targeted logging or assertions rather than speculative edits.
5. Once the root cause is found, write a regression test that fails
   before the fix and passes after it.

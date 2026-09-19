---
name: security
description: Security review guidelines covering injection, secrets, and authorization. Use when reviewing code for vulnerabilities or implementing anything that handles user input, auth, or secrets.
license: MIT
metadata:
  category: quality
  test0.tags: security,review
---
# Security Skill

## When to use this skill
Reviewing any code that handles user input, authentication/authorization,
external requests, or secrets — or implementing such code.

## Instructions
1. Never trust user input; validate and sanitize at every trust boundary.
2. Watch for injection classes: SQL, command, template, and NoSQL injection.
3. Check for SSRF (unvalidated outbound requests using user-controlled
   URLs) and path traversal (unvalidated file paths).
4. Verify secrets are never hard-coded, logged, or echoed back in error
   messages.
5. Confirm authorization checks exist on every sensitive action — do not
   assume authentication alone is sufficient.
6. Flag `eval`, dynamic `exec`, or unsandboxed deserialization of
   untrusted data.

---
name: security
version: 1.0.0
description: Security review guidelines
tags: [security, review]
---
# Security Skill

- Never trust user input; validate and sanitize at boundaries.
- Watch for injection (SQL, command, template), SSRF, and path traversal.
- Check secrets are not hard-coded or logged.
- Verify authz checks exist on every sensitive action, not just authn.
- Flag any use of `eval`, dynamic `exec`, or unsandboxed deserialization.

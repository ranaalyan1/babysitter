# v0.1 architecture and boundaries

The architecture below remains the protocol runtime foundation. The explicitly
approved v0.2 expansion adds one native Claude Code hook adapter, documented in
[CLAUDE_CODE.md](CLAUDE_CODE.md), with an [additive contract](CLAUDE_ADAPTER_SCHEMA.md).
It reuses verification, checkpoints and events; it does not replace this runtime.

```text
CLI (init/start/doctor/trace)
             │
FastAPI protocol adapters ────────── one OpenAI-compatible HTTP provider
             │                           ▲
             ▼                           │ failure-context retry
 Observe ─ Validate ─ Repair ─ Execute ─ Verify ─ Recover ─ Escalate
    │          │          │       │         │       │
    └──────────┴──────────┴───────┴─────────┴───────┘
                            │
                  SQLite v1 event/task state
                  + content-addressed checkpoints
```

## Lifecycle ownership

The implementation uses modules with lifecycle responsibilities, not pretend
parallel agents or a new framework:

- **Observe:** `state.py`, protocol request/result events, persisted task/session/
  step identity. Observed plans can live in the frozen `plan_json` field; v0.1
  does not parse prose into an invented plan or capture hidden chain of thought.
- **Validate/Repair:** `repair.py`, JSON Schema 2020-12, declared tools only,
  argument types/required fields, local-only schema refs, common malformed JSON,
  lossless numeric/boolean coercion, required values only from schema defaults,
  constants or singleton enums. Unknown required values trigger contextual retry.
- **Execute:** external client in relay mode; only `tools.py` read/write in managed
  mode. Whole batches validate before any local tool executes.
- **Verify:** `verify.py`, actual configured commands in the project root, bounded
  output, timeouts/process-group cleanup, before/after fingerprints and changed-file
  diff including nonignored untracked files. `git diff --check HEAD` detects
  whitespace/conflict-marker errors including staged changes. The content-addressed
  baseline diff attributes new changes separately from preexisting dirty changes.
- **Recover:** `runtime.py` + `project.py`, classify, preserve failed bytes, restore
  baseline, pass evidence back, bound attempts, detect repeated identical calls
  against unchanged content. Signatures persist across relay continuations.
- **Escalate:** a single deterministic same-step consecutive-failure threshold.
  No scores, judge model, routing, benchmarks or best-of-N.

## Evidence contract

`verified_complete` means the configured test and typecheck commands exited zero,
git inspection passed, no file content/mode changed during verification, and no
tool calls remain pending. It does **not** prove arbitrary natural-language intent
or compensate for inadequate tests. Project operators own meaningful commands.
A final model assertion is never evidence. Missing commands explicitly block
success. The final answer is rechecked even after a successful write batch.

v0.1 classifies typecheck failures under `syntax-fail`; this label includes static
errors beyond parser errors. Other classes: tool-error, test-fail,
no-progress-loop, provider-error, unsafe-change and verification-unavailable.
No-progress detection means three identical proposed tool batches on the same
project fingerprint; it is not a semantic measure of model reasoning.

## Safety and limitations

1. **Trusted local workspace, not a security sandbox.** Tests/typecheck execute
   repository code as the current user. That code can perform network access or
   alter files outside the supervised inventory. Use OS/container isolation for
   untrusted projects. No claim of preventing hostile code execution.
2. Managed file tools refuse absolute/traversal paths, symlinks, `.git`,
   `.babysitter`, ignored files, `.env*`, `babysitter.json` and `.gitignore`.
   Read/write limits are 1 MB per file. Checkpoint size defaults to 25 MB and
   fails closed; increase explicitly for larger repositories. Git submodules and
   special files are unsupported and fail closed.
3. Relay policy validates known path fields and allowlists recognized command
   fields against exact configured verification argv. It cannot infer arbitrary
   custom-tool semantics or control what an external tool actually executes.
   Validation is not a sandbox, and supervision is not an IDE execution trace.
4. Verification subprocesses receive a small environment allowlist, not provider
   credentials. Python subprocesses use an isolated bytecode cache prefix with
   bytecode writes disabled, so rapid same-size edits and rollback cannot reuse
   stale timestamp-based `.pyc` files. They still have the user's filesystem permissions. Provider
   requests do not follow environment HTTP proxies (`trust_env=False`).
5. Snapshots cover tracked and nonignored untracked files (not Git internals or
   ignored build outputs). Baseline paths stay covered if external ignore policy
   changes. Failed bytes are durable before rollback; corruption or unsafe paths
   halt recovery rather than silently losing changes. Checkpoints are retained
   indefinitely in v0.1; prune manually only after inspecting them.
6. No concurrent-writer guarantee: a runtime/project lock serializes Babysitter,
   not editors or other programs. A content fingerprint detects observed changes
   during checks, not every transient filesystem operation. Use a dedicated
   worktree. The filesystem checks are not hardened against a hostile concurrent
   symlink-swap attacker. File mtimes, ACLs/xattrs and Git index mutations are not
   checkpointed; content, regular modes and symlink targets are.
7. One pending relay task owns a worktree. Restart preserves that task. An
   interrupted in-flight turn is failed on restart without discarding contents.
   No lease/session reaper or background autonomous execution exists in v0.1.
8. Auth is optional on loopback; non-loopback binding requires a local token.
   Host checks without auth protect against DNS rebinding; browser Origin requests
   are rejected. There is no dashboard, CORS integration or account system.
9. SQLite event payloads contain code, tool results and command output. Common
   credential labels and bearer strings are redacted; arbitrary secret values may
   remain. File snapshots intentionally preserve original bytes. Keep `.babysitter`
   private and out of Git. Sending protocol content to an upstream is an explicit
   local-operator choice; local Ollama keeps that boundary on the machine.
10. Anthropic compatibility is a documented text/function subset, not a promise
    of full SDK/Claude Code feature support. Streams buffer until supervised.
    Provider outages consume the same bounded retry budget; no multi-provider
    fallback, routing or unofficial authentication mechanisms exist.

## Schema review status

The shared v1 schema was defined and self-reviewed before implementation, then
kept stable through verification and protocol integration. Human/external review
is still pending. See `SCHEMA.md` for the frozen envelope and review checklist.

## v0.4 presentation layer (approved scope expansion)

The local console is a separate read-only application, not an execution dashboard
or cloud control plane. `console.py` uses existing SQLite state with `mode=ro` and
`query_only`, bounds evidence previews, and never acquires runtime ownership.
Packaged UI assets and offline documentation require no frontend build or CDN.
The original protocol app and its browser-origin rejection are unchanged.

Real non-loopback console API access requires its own `BABYSITTER_UI_TOKEN`.
Public demo mode uses synthetic fixtures and never reads the selected project.
See [interface contract](INTERFACE_CONTRACT.md) and [console guide](CONSOLE.md).

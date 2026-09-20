# Protocol & CLI reference

The original runtime integration guide. For the product overview and native-agent setup, see [README](../README.md).

## Configure and start protocol mode

Run these in the **target repository**, with `aletheia` on your PATH:

```sh
aletheia init \
  --provider-url http://127.0.0.1:11434/v1 \
  --model qwen2.5-coder:7b \
  --test 'python -m pytest -q' \
  --typecheck 'python -m mypy src' \
  --managed-tools

aletheia doctor
aletheia start
```

`init` writes `aletheia.json` and excludes `.aletheia/` and `.env` from Git.
It does not overwrite existing configuration or guess verification commands.
Commands are parsed into argv arrays and executed **without a shell**. Configure
commands that genuinely cover your project; `true` is not meaningful evidence.
Use absolute executable paths if starting outside your project's virtualenv.

- Default listener: `127.0.0.1:8030`.
- Optional stronger model: `init --stronger-model MODEL` (same provider).
- Provider credentials: environment variable `ALETHEIA_PROVIDER_API_KEY`.
- Optional local server token: `ALETHEIA_LOCAL_TOKEN`.
- Binding `--host 0.0.0.0` **requires** a local token. Clients send
  `Authorization: Bearer TOKEN` or Anthropic's `x-api-key: TOKEN`.
- `--root /path/to/project` is a global CLI option, before the subcommand.
- `doctor --offline` checks local prerequisites without contacting the provider.

### Managed mode: autonomous local demo/task

Only `read_file` and `write_file` execute locally. Both the configuration opt-in
and the request header are required. Built-in schemas are injected automatically.
No model-issued shell execution exists in managed mode.

```sh
curl http://127.0.0.1:8030/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Aletheia-Execute: true' \
  -d '{
    "model": "aletheia",
    "messages": [{"role":"user","content":"Fix the failing addition test in calc.py. Read the files first."}]
  }'
```

Writes are verified after each complete tool batch. Failed changes are saved in
a content-addressed checkpoint before rollback. The model receives actual failure
output plus an explicit rollback notice, then gets another attempt. After two
consecutive failures on one step, the next attempt uses the configured stronger
model. A verified batch advances the step and resets to the base model.

### Relay mode: existing coding client owns execution

Without `X-Aletheia-Execute: true`, declared tools are **not** run locally:

1. Send a normal protocol request with tool declarations.
2. Receive schema-valid, policy-checked tool calls. State is `awaiting_tools`,
   **not** complete.
3. Execute them in the target worktree. Return the normal tool-result messages,
   the same tool declarations, and **`X-Aletheia-Task` from the response**.
4. Aletheia independently runs checks before allowing a terminal answer.
   Failure may cause another clean tool-call response for your client to execute.

Response headers:

| Header | Meaning |
| --- | --- |
| `X-Aletheia-Task` | Persistent task identity; required on continuation |
| `X-Aletheia-Session` | Session identity; optionally supply when creating a task |
| `X-Aletheia-State` | `awaiting_tools`, `verified_complete`, etc. |
| `X-Aletheia-Verified` | `true` only after terminal verification passes |

One outstanding task owns a project. A second task is rejected while a relay tool
batch is pending. A process lock prevents two servers from supervising the same
worktree. These locks **cannot** prevent your editor or external agents changing
files. Do not share the worktree with concurrent writers.

**Protocol relay alone is not a drop-in Claude Code/Cursor/Codex integration.**
Claude Code and Codex users can use the native hook integrations described in
[README](../README.md); OpenCode has an owned CLI wrapper. A Cursor adapter is
not implemented. A proxy sees only messages passing
through it; relay clients must still preserve the task header. Tool result strings
from OpenAI have no standardized error flag; explicit JSON `error` / `is_error`
and Anthropic `is_error` are recognized, and checks remain independent.

## Protocol support

- `POST /v1/chat/completions`: text and function tools; one choice.
- `POST /v1/messages`: Anthropic text, system text, tool_use/tool_result translated
  to the same single OpenAI-compatible upstream.
- `GET /v1/models`: forwards that upstream's model listing.
- Use `model: "aletheia"` or the configured base model. The runtime, not the
  caller, selects the stronger model under the failure-counter rule.
- `stream: true` is supported as **buffered SSE**, emitted only after validation
  and any required verification. It is deliberately not low-latency token relay.
- Basic sampling, max_tokens, stop and tool_choice fields are supported.
  Images, audio, thinking blocks, Responses API, multiple choices, and unknown
  request fields are rejected rather than silently treated as supervised.

Missing test/typecheck commands yield HTTP **409** and
`verification_unavailable`, never a success-looking answer. Exhausted retries
produce HTTP **422**, persisted failure evidence and a task ID. The total model
request budget (`max_attempts`, default 6) is persistent across relay requests;
`max_tool_rounds` bounds one request's loop. No infinite retries.

## Inspect evidence

```sh
aletheia trace                         # all tasks, ordered events, checkpoint paths
aletheia trace TASK_ID                 # one task
aletheia trace TASK_ID --metrics
aletheia trace TASK_ID --checkpoint CHECKPOINT_ID
```

SQLite lives at `.aletheia/state.sqlite3`. Checkpoint manifests and file blobs
live under `.aletheia/checkpoints/`. A failed snapshot remains inspectable after
rollback. Preexisting dirty/untracked files and executable modes are preserved;
Git index/history are never reset or stashed. Trace exposes command evidence,
repairs, retries, actual selected models and changed files. Secrets are redacted
on a best-effort basis, **not** guaranteed scrubbed from arbitrary source/output.
Treat the entire state directory as sensitive local project data.

An interrupted managed turn is marked failed on restart, retaining its worktree
and checkpoints for inspection; no speculative rollback occurs after downtime.
An `awaiting_tools` task can resume after restart using its task header.

## Run the defining demo (no credentials)

```sh
python scripts/demo.py --http
python scripts/demo.py --http --fail-twice
```

With `--http`, the demo starts the actual CLI server in a separate process on an
OS-assigned port, authenticates with an ephemeral local token, and sends real TCP
requests through both runtime and provider. It shuts down the server afterward.
Omit `--http` for the faster in-process ASGI path.

These use a clearly labeled **scripted faulty-model fixture** speaking real HTTP,
not a real LLM or quality benchmark. The initial failing tests are intentional:
**the final task must be `verified_complete`**, not merely a model claim.
Every other stage is real:

```text
malformed tool call → repaired → file written → pytest FAIL
→ failed bytes checkpointed → baseline restored → failure context fed back
→ corrected file written → pytest PASS + mypy PASS + diff checked
→ terminal checks PASS → verified_complete
```

The second variant proves `weak → weak → strong → weak` step-only escalation.
Full traces and disposable demo repos stay in ignored `.aletheia/`; compact
reports are in `docs/*-results.json`.

The same loop was also executed against actual ItsDangerous and Click suites.
See [reproduction instructions and metrics](VALIDATION.md). Actual weak/free
model performance and time saved versus a human baseline remain **unmeasured**.

> Aletheia lets AI agents act autonomously without letting them fail silently.

# OpenCode owned CLI supervision — v0.3

Tested with official **OpenCode 1.18.31**. This integration supervises an owned
`opencode run --format json` process. It is **not** an idle-notification plugin,
TUI integration, or a claim that every native action is intercepted.

## Setup and run

Install/authenticate OpenCode through its official mechanism. Use a dedicated git
worktree with a commit, install Aletheia, and configure meaningful checks:

```sh
aletheia init --test 'python -m pytest -q' --typecheck 'python -m mypy src'
# For an existing config, edit it rather than running init again.
aletheia doctor --offline
aletheia opencode status
aletheia opencode run 'Fix the failing parser tests'
# Optional native selection and explicit executable:
aletheia opencode run 'Fix the parser' \
  --executable /absolute/path/to/opencode --model provider/model --timeout 600
```

No plugin/global configuration is installed, so there is no uninstall command.
Normal `opencode` TUI invocations are **not supervised**. No proxy server or
Aletheia provider credentials are needed. Native authentication, configured
providers/models/plugins and permissions remain OpenCode's responsibility.
The wrapper never passes `--auto`, `--attach`, `--share`, permission-bypass flags,
or an agent override. Native noninteractive permission requests may be rejected
by OpenCode; the wrapper does not approve them on your behalf.

Only **wrapper exit 0 and `"verified": true`** mean successful supervision. Its
final JSON includes task ID, native session ID, verification status and the final
native text **only after** independent checks pass. Unverified model text is not
streamed as a successful final answer. Full emitted observations are inspectable
through `aletheia trace TASK_ID` and checkpoint inspection.

## Lifecycle

- Hold the same project lock used by native hooks/protocol supervision.
- Snapshot the worktree, including pre-existing uncommitted files in snapshot scope.
- Own the native child process group; send the prompt through stdin, not a shell.
- Parse bounded JSONL: consistent `sessionID`, paired steps, completed/error tool
  parts, final `step_finish.reason = stop`, no native session error, clean exit.
- Stop the owned group before independent test/typecheck/git-diff verification.
- On failed checks, save unsuccessful contents before restoring the baseline;
  pass bounded failure evidence to `opencode run --session ID` for correction.
- Allow at most `min(max_attempts, 3)` native invocations. An unchanged rolled-back
  baseline cannot earn success. Log escalation requests without switching models.

Native tool errors prevent success for that turn even if tests pass. Missing
checks produce `verification_unavailable`. Unclean process exit, timeout,
unsupported/malformed/truncated output, changed control files or concurrent
verification edits halt without discarding the current files. Failed snapshots
are recorded when possible; no unsafe automatic rollback is attempted across an
uncertain process boundary. SIGINT stops the owned group and records failure.
A hard-killed supervisor can leave a stale active task: inspect evidence and end
any remaining native work; use a fresh dedicated worktree rather than silently
resetting or stealing its ownership.

Limits: 2 MB per JSONL line, 16 MB stdout/10,000 events per native invocation,
`max_output_bytes` per persisted event/stderr preview, configurable per-invocation
`--timeout` (default 600s). Verification command timeout is separate, from
`aletheia.json`. No cost/token ceiling is inferred for native model calls.

## Limits you should rely on

This is **post-execution supervision**, not a pre-tool safety gate. A native tool
may already have changed files before its result is emitted. JSONL describes
emitted observations, not a lossless action audit: in the installed CLI fixture,
the first read was not emitted, while subsequent tool results and final steps
were observed. Counts therefore mean **observed results only**. The parser can
detect malformed/incomplete final steps, not every internally omitted event.

Only foreground main-agent work is supported. Detected `task`/subagent tool use
halts, but this cannot prevent delegation that already happened. Do not enable
background/subagent work or attach external servers. Killing the owned process
group is not an OS sandbox and cannot guarantee quiescence of escaped/detached
processes. Use native permissions and a dedicated worktree.

Repository verification configuration and named OpenCode config files are pinned
per task; global native configuration and arbitrary plugin code are not a
Aletheia policy boundary. Ignored/generated files are outside snapshot scope.
Checks prove configured tests, not every intended requirement or resistance to
malicious edits to tests. Model effectiveness/time savings remain unmeasured.

## Reproduce

```sh
python scripts/native_agents_demo.py opencode --executable /absolute/path/to/opencode \
  --output .aletheia/opencode-report.json
ALETHEIA_OPENCODE_BIN=/absolute/path/to/opencode pytest -q tests/test_native_agents.py
```

The fixture uses the actual OpenCode binary/tools, isolated home/XDG directories,
a local scripted Chat Completions endpoint, and explicitly permitted test read/
write tools in its disposable project. No real model/credentials or permission
bypass flag is used. [Small-fixture results](opencode-demo-results.json) ·
[Click upstream-suite results](opencode-real-project-results.json) ·
[Shared contract](ADAPTERS_V03_CONTRACT.md) · [Official CLI docs](https://opencode.ai/docs/cli/).

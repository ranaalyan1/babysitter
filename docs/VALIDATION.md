# Validation report — 2026-09-20

## What was actually run

- **61 automated tests passed** for schema persistence, repair, real verification,
  rollback, recovery/escalation, both protocols, buffered SSE, restart, local
  authentication, CLI, metrics, and negative cases.
- **mypy passed** for all 13 runtime modules.
- The defining autonomous fault-injection demo ran end to end, including actual
  file writes, pytest, mypy, git checks, SQLite events, preserved failed contents,
  rollback and a final `verified_complete` task.
- An additional demo forced two consecutive failures and verified the exact
  model sequence **weak → weak → strong → weak**.
- The same runtime/protocol/provider path ran against **two real repositories**,
  not just the small regression fixture.

**Important:** the provider in these runs was a deterministic faulty-model fixture
served over real HTTP. The FastAPI app was called via its ASGI protocol interface.
These prove runtime integration and deterministic recovery mechanics, **not**
real-model capability, provider-specific interoperability beyond the supported
wire subset, or a production autonomous-task success rate. There were no human
interventions during the four runs; the fixture was deliberately programmed to
consume failure context and propose the known correction.

## Captured runs

| Run | Initial evidence | Corrected evidence | Escalations | Wall time |
| --- | --- | --- | ---: | ---: |
| Defining demo | 1 failing test | pytest + mypy + diff pass | 0 | 2.354 s |
| Escalation demo | 2 failed verification rounds | all checks pass; returns to base model | 1 | 2.918 s |
| ItsDangerous | 40 failures / 257 passing | **297 passing**, mypy: 8 source files | 0 | 3.861 s |
| Click | 15 failures / 2,044 passing | **2,059 passing**, mypy: 28 source files | 0 | 21.107 s |

Every run performs one more verification before releasing the final completion.
Click also reported 24 skipped, 31,000 deselected stress cases and 1 expected
failure, using the project's default test selection. Those were **not** counted
as passing. Times include local runtime/verification, not real model latency.

Real-project revisions:

- `pallets/itsdangerous`: `672971d66a2ef9f85151e53283113f33d642dabd`
- `pallets/click`: `6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1`

Faults: remove ItsDangerous base64 padding stripping; inject an incorrect prefix
into Click's short-help output. Recovery restores original behavior plus a
comment, leaving a real inspectable final diff. These are injected regressions,
not claims that upstream had bugs.

Raw compact reports include command argv, exit codes, output tails, fingerprints,
model sequences, task IDs and trace locations:

- [Defining demo](demo-results.json)
- [Escalation demo](escalation-results.json)
- [Real-project runs](real-project-results.json)

Full events/checkpoints are local ignored artifacts. Absolute trace paths in the
reports describe this execution environment; they are not portable downloads.

## Metrics (four controlled runs, not a model benchmark)

| Requested metric | Observed result / honest boundary |
| --- | --- |
| Malformed tool-call recovery | **4 / 4 = 100%**, deterministic repair of injected trailing-comma JSON |
| Verified tasks without human intervention | **4 / 4 = 100%** in scripted runs only |
| Failures caught before completion | **5 failed verification rounds**; none released as a successful completion |
| Verification catch rate | **5 / 13 = 38.46%** verification runs failed; this is a check-failure fraction, not recall |
| Escalation rate | **1 / 4 = 25%** of tasks used the stronger fixture model |
| Recovery without escalation | **3 recovered steps**; observable proxy only |
| Unnecessary escalations avoided | **Unmeasured**; no counterfactual/judge was fabricated |
| Tasks completed on base model only | **3 / 4** under the fixture |
| Tasks completed on a real weak/free model | **Unmeasured**; requires an actual model endpoint |
| Time saved versus manual recovery | **Unmeasured**; no timed human baseline |

`aletheia trace --metrics` computes counts and denominators directly from the
event log. Unavailable values are JSON `null`, not invented zeroes. Failed tasks
remain in the success-rate denominator; active tasks are reported separately via
total versus terminal task counts.

## Reproduce

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
mypy aletheia
python scripts/demo.py --output .aletheia/demo-report.json
python scripts/demo.py --fail-twice --output .aletheia/escalation-report.json
```

For real projects, use disposable **clean** clones outside this runtime checkout:

```sh
mkdir -p ../validation-repos
git clone https://github.com/pallets/itsdangerous.git ../validation-repos/itsdangerous
git clone https://github.com/pallets/click.git ../validation-repos/click
# For exact reproduction, check out the two detached revisions listed above.
pip install -e ../validation-repos/itsdangerous -e ../validation-repos/click freezegun
python scripts/validate_real_projects.py ../validation-repos \
  --output .aletheia/real-project-report.json
```

The real-project script rejects dirty checkouts, intentionally writes an injected
fault, runs the upstream suites and typechecks, then leaves the verified comment
and evidence. It does not silently reset your checkout. Use new clean disposable
clones for another run.

## Remaining acceptance boundary

The runtime, verification engine and credential-free deterministic demo are
implemented and tested. The schema has an implementation self-review; external
review is pending. A real weak/free model run is still needed before claiming
real-world model reliability gains. This repository does **not** pretend a proxy
has complete visibility into an IDE or that passing a suite proves every user
requirement. No out-of-scope integrations or cloud features were added.

## v0.3 native-agent validation

Executed 2026-09-20, with official clients installed outside this repository.
The adapter contract was written before implementation; core schema stays v1,
Codex tables are additive, and Claude v0.2 regressions remain covered.

Final v0.3 checks: **190 tests passed in 144.59s**, including all three official
native clients; **mypy clean across 20 source files**. Editable installation and
wheel build passed; the v0.3.0 wheel was inspected for both new adapters, shared
lifecycle code and additive SQL package data. `git diff --check` passed.

| Native client | Target | Injected failure → recovered evidence |
| --- | --- | --- |
| Codex 0.155.1 | Addition fixture | Failed assertion → tests/typecheck/git-diff passed; one task, two observed patch results |
| OpenCode 1.18.31 | Addition fixture | Failed assertion → tests/typecheck/git-diff passed; same native session, three emitted tool results |
| Codex 0.155.1 | ItsDangerous, pinned revision above | 40 failed / 257 passed → **297 passed**; mypy 8 files; git-diff passed |
| OpenCode 1.18.31 | Click, pinned revision above | 15 failed / 2044 passed → **2059 passed**; mypy 28 files; git-diff passed |

Click additionally reported **24 skipped, 31,000 deselected, 1 xfailed** in both
rounds, under the upstream default test selection. These are not passes. The
new adapter/project pairings above were tested; not every agent/repository
combination. Each successful recovery retained its original task/checkpoint and
logged a real rollback; no human intervention was needed within these scripted
runs. That is not a measure of real-model autonomy or manual time savings.

Reports: [Codex fixture](codex-demo-results.json),
[OpenCode fixture](opencode-demo-results.json),
[Codex / ItsDangerous](codex-real-project-results.json),
[OpenCode / Click](opencode-real-project-results.json).
Absolute paths locate local ignored evidence, not portable deliverable files.

**Important:** real official agents/tools, but scripted local model endpoints and
isolated native homes; no inherited real provider credentials. Codex's fixture
uses an explicitly vetted **test-only** hook trust bypass; production install
never does. OpenCode's fixture project explicitly permits read/write tools; the
wrapper never adds auto-approval. A known Codex model identifier selects native
tool metadata, not an actual cloud model. Native model-selection metrics are
agent-owned and excluded from base-model-only claims.

OpenCode's installed JSONL CLI did not emit the initial read in these runs. Its
observed tool count is therefore not a complete native action count. No hidden
calls or plans were fabricated. The wrapper checks the emitted final-step
structure and independently verifies the actual filesystem after process exit.

### Reproduce current tests

```sh
ALETHEIA_CLAUDE_BIN=/absolute/path/to/claude \
ALETHEIA_CODEX_BIN=/absolute/path/to/codex \
ALETHEIA_OPENCODE_BIN=/absolute/path/to/opencode pytest -q
mypy aletheia
python scripts/native_agents_demo.py codex --executable /absolute/path/to/codex
python scripts/native_agents_demo.py opencode --executable /absolute/path/to/opencode
```

The native-agent tests skip explicitly if their executable environment variables
are absent. Contract/failure-injection tests still run. Coverage includes path
and rename guards, no permission auto-approval, incomplete/running calls,
continuation budget preservation (including late callbacks), ownership conflicts,
reversible installation, malformed/oversized/truncated streams, missing checks,
process timeout, stale configuration and baseline-only false completion.

For the real upstream suites, create **new clean disposable clones**, use the
pinned detached revisions listed earlier, and install `freezegun` alongside the
Aletheia dev/test dependencies. No editable upstream install is necessary:
the fixture sets `PYTHONPATH` to that checkout's `src` for native verification.

```sh
python scripts/native_agents_demo.py codex --executable /absolute/path/to/codex \
  --project-path /path/to/disposable/itsdangerous --output .aletheia/codex-real.json
python scripts/native_agents_demo.py opencode --executable /absolute/path/to/opencode \
  --project-path /path/to/disposable/click --output .aletheia/opencode-real.json
```

`--project-path` intentionally injects regressions. It accepts only the two named,
clean, pinned checkouts; it never resets your worktree. It leaves the verified
comment and supervision evidence. Use fresh clones for subsequent runs.

## v0.4 console & presentation validation

Executed 2026-09-20. **207 tests passed in 165.45s**, including the three official
native-agent integration tests. **Mypy: 22 source files clean.** Editable install
and the v0.4.0 wheel build passed; the wheel was inspected for console code,
static assets, self-hosted font/license, offline guides and native adapter SQL.

The 17 new Python checks cover empty/no-write workspaces, demo isolation,
truthful record counts, SQLite query-only enforcement, token and origin gates,
CSP, read-only HTTP methods, symlink rejection, canonical checkpoint ownership,
secret-pattern redaction, bounded event windows, missing/malformed retained
artifacts, asset packaging and synchronized offline documentation.

The optional Playwright browser harness exercised task search/status filters,
evidence/checkpoint dialogs and file previews, trace downloads, agent setup,
offline guides, command-palette search, browser preferences, mobile navigation,
token entry without storage persistence, empty/error states, and escaped
untrusted task text. It recorded **no uncaught browser errors** and no horizontal
page overflow at the tested 390 px mobile width.

Automated axe WCAG 2 A/AA checks reported **zero violations in ten tested views
and states**: overview, task evidence, tasks, verification, checkpoints,
integrations, workspace, setup, offline documentation, and mobile overview.
This is a bounded automated check, not a comprehensive accessibility audit or
certification. [Machine-readable browser report](console-validation-results.json).

The published desktop/mobile screenshots are actual browser captures of explicitly
labeled synthetic demo data, not images generated to imply a functioning backend.
Real state is exercised separately by the read-only API regressions. Public
presentation mode reads no repository evidence. No new real-model quality claims
are made, and the core schema and execution/protocol trust boundaries are unchanged.

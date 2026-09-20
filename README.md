<p align="center">
  <img src="docs/brand/readme-banner.svg" alt="Babysitter. Your agents build. We check the work." width="100%">
</p>

<p align="center">
  <strong>A local supervision runtime for AI coding agents.</strong><br>
  Models generate actions. Agents coordinate actions. Babysitter makes sure those actions actually work.
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#the-local-console">Console</a> ·
  <a href="#choose-your-integration">Integrations</a> ·
  <a href="docs/VALIDATION.md">Evidence</a> ·
  <a href="docs/CONSOLE.md">Documentation</a>
</p>

---

## “Done” should mean checked.

Coding agents move quickly. Sometimes they also skip a failing test, repeat a bad
edit, or announce success before the work is ready.

**Babysitter adds an evidence requirement around the agent you already use.** It
observes supported actions, validates what it can, independently runs your checks,
and gives failures a bounded path to recovery. Unsuccessful changes are retained
before rollback. A model's confidence never substitutes for verification.

```text
Observe → Validate → Repair → Execute → Verify → Recover → Escalate
```

Local-first. No cloud account. No auth scraping. No invented time-savings claims.

## The local console

<p align="center">
  <img src="docs/brand/console-desktop.png" alt="Babysitter's local console: task states, verification evidence, checkpoint counts, and the supervision loop. Screenshot shows labeled synthetic demo data." width="100%">
</p>

**New in v0.4:** a complete visual identity and a read-only interface for the runtime.

- **Overview** — recorded task states, failed verification rounds, checkpoints, and recent activity.
- **Tasks** — search, status filters, event timelines, and loaded-trace JSON export.
- **Verification** — independent command output, exit codes, timing, and failures.
- **Checkpoints** — inspect retained manifests and file previews without restoring anything.
- **Agent integrations** — copyable setup instructions, with capability limits made explicit.
- **Workspace** — local configuration and browser-only display preferences.

```sh
babysitter ui          # Read evidence in the current repository
babysitter ui --demo   # Explore clearly labeled synthetic data; reads no project state
```

Open **http://127.0.0.1:8040**. To inspect a different repository:

```sh
babysitter --root /path/to/project ui
```

The console never launches agents, executes tests, grants permissions, restores
files, or changes task states. It can run beside a native agent without taking
the project's supervisor lock. Its synthetic demo is **not** evidence of real
model performance. [Console setup and security →](docs/CONSOLE.md)

## Quick start

**Requirements:** Python 3.11+, Git, and Linux/macOS. Your target project must be a
git repository with at least one commit. Use a dedicated worktree and meaningful
project-specific tests.

### 1. Install from this checkout

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

This installs Babysitter, not an AI model or a native coding agent. Install and
authenticate Claude Code, Codex, or OpenCode through their official instructions.
No published package availability is implied by the project name.

### 2. Configure the target repository

With `babysitter` on your PATH, run this in the repository you want supervised:

```sh
babysitter init \
  --test 'python -m pytest -q' \
  --typecheck 'python -m mypy src'

babysitter doctor --offline
```

Replace these example commands with checks that cover **your** project. Commands
are argv arrays, not shell scripts. Use absolute interpreter paths if needed.
`init` creates `babysitter.json` and excludes `.babysitter/` and `.env` from Git;
it will not overwrite an existing configuration.

### 3. Choose one integration

#### Claude Code

```sh
babysitter claude install
babysitter claude status
claude
# Review the installed commands in /hooks, then start supervised work.
```

[Claude Code guide →](docs/CLAUDE_CODE.md)

#### Codex

```sh
babysitter codex install
babysitter codex status
codex
# Trust the project and review/trust the exact installed definitions in /hooks.
```

The installer does not bypass hook trust or change sandbox/permission settings.
[Codex guide →](docs/CODEX.md)

#### OpenCode

```sh
babysitter opencode run 'Fix the failing tests'
```

Use this owned CLI wrapper—not a normal OpenCode TUI session. Only wrapper exit 0
with `"verified": true` is successful supervision. [OpenCode guide →](docs/OPENCODE.md)

### 4. See what actually happened

```sh
babysitter ui
babysitter trace
babysitter trace TASK_ID
babysitter trace TASK_ID --metrics
babysitter trace TASK_ID --checkpoint CHECKPOINT_ID
```

## Choose your integration

These are different contracts, not blanket agent compatibility.

| Integration | What Babysitter sees | Completion / recovery | Setup |
| --- | --- | --- | --- |
| **Claude Code** | Supported native command hooks | Stop checks, retained failures, bounded continuation | Project-local hooks |
| **Codex** | Supported hooks, Bash inputs and patch paths | Stop checks; same task/checkpoint/budget across recovery | Project-local hooks; native trust required |
| **OpenCode** | Emitted JSONL from an owned CLI process | Checks after clean process exit; same-session retry | Wrapper, no plugin |
| **Protocol runtime** | OpenAI-compatible / Anthropic-compatible protocol traffic and independent filesystem checks | Managed-tool or relay lifecycle, step-only escalation | Explicit HTTP integration |

**DeepSeek harness and additional agents are not implemented.** Their scope remains
deferred. No adapter manages native provider credentials or silently switches a
native agent's model.

For protocol mode, configure one OpenAI-compatible upstream and start the local
API with `babysitter start` (default port 8030). Browser UI and protocol API are
separate services with separate trust boundaries.
[Full protocol setup, headers, managed/relay modes, and examples →](docs/PROTOCOL.md)

## Recovery you can inspect

1. Capture the starting worktree, including existing uncommitted work in snapshot scope.
2. Observe supported agent activity without inventing hidden plans or tool calls.
3. Run your **tests + typecheck + git-diff** and check stable file fingerprints.
4. If checks fail, preserve unsuccessful contents in a content-addressed checkpoint.
5. Restore the baseline only when safe, then return bounded failure context for a correction.
6. Stop with an explicit not-verified outcome when evidence or retry budget is exhausted.

A restored baseline is not proof that a failed task was fixed. Missing checks,
unfinished tools, stale verification, and uncertain process boundaries do not
produce successful completion. Native recovery is capped at `min(max_attempts, 3)`
Stop attempts / owned CLI invocations. Native escalation requests are distinct
from actual model switches.

## Evidence, not a benchmark

Official client integration tests have exercised Claude Code **2.1.278**, Codex
**0.155.1**, and OpenCode **1.18.31** against isolated, scripted local model endpoints.
Those are real clients and native tools, but **not real-model quality tests**.

| Controlled upstream-repository test | Injected failure | Verified recovery |
| --- | --- | --- |
| Codex + ItsDangerous | 40 failed / 257 passed | **297 passed**, mypy 8 files, git-diff passed |
| OpenCode + Click | 15 failed / 2044 passed | **2059 passed**, mypy 28 files, git-diff passed |

Click also reported 24 skipped, 31,000 deselected, and 1 xfailed; these were not
counted as passes. See [versions, pinned revisions, reports and reproduction](docs/VALIDATION.md).
Real weak/free model effectiveness, market superiority, and manual time savings
are **unmeasured**.

## Boundaries worth knowing

- **One agent/supervisor per worktree.** A read-only console is fine alongside it;
  competing native/protocol supervisors are not.
- Hooks and process ownership are **not an OS sandbox** or a complete action audit.
  Native permissions, trusted configuration and isolated worktrees still matter.
- OpenCode is post-execution supervision, not pre-tool interception. Its emitted
  JSONL can omit internal activity; only observed results are counted.
- Ignored/generated files and external side effects are outside checkpoint scope.
  Do not run detached/background agents or unsupported subagent workflows.
- Checks prove the configured checks—not every natural-language requirement, nor
  resistance to malicious changes to the tests themselves.
- The real console exposes source/evidence to authorized viewers. Keep it private.
  Non-loopback serving requires `BABYSITTER_UI_TOKEN`; the protocol API separately
  uses `BABYSITTER_LOCAL_TOKEN`. Never publish credentials or expose execution APIs.

[Security policy →](SECURITY.md) · [Architecture →](docs/ARCHITECTURE.md) ·
[Frozen schema →](docs/SCHEMA.md)

## Develop and validate

```sh
pytest -q
mypy babysitter
python scripts/demo.py --output .babysitter/demo-report.json
```

To include official native clients (otherwise those tests explicitly skip):

```sh
BABYSITTER_CLAUDE_BIN=/absolute/path/to/claude \
BABYSITTER_CODEX_BIN=/absolute/path/to/codex \
BABYSITTER_OPENCODE_BIN=/absolute/path/to/opencode pytest -q
```

Browser interaction and accessibility checks have a separate optional Node test
harness; no Node runtime or frontend build is required to use the console.
[Contribution and browser-test instructions →](CONTRIBUTING.md)

## Find your way around

```text
babysitter/
  adapters/           Native hooks and owned OpenCode runner
  console.py          Separate read-only console API
  web/                Packaged UI, original SVG assets and local font
  runtime.py          Supervision lifecycle
  verify.py           Independent command evidence
  project.py          Checkpoints and inspectable rollback
  state.py            Frozen task/event persistence
  server.py           Protocol API (unchanged browser boundary)
docs/                 Setup, contracts, evidence and design guidelines
scripts/              Reproducible validation and asset-sync tools
tests/                Contract, regression, security and browser checks
```

[Console](docs/CONSOLE.md) · [Brand kit](docs/BRAND.md) ·
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

### Licensing

A project-wide license has not yet been selected; no new license grant is implied.
The bundled Manrope font is distributed under the
[SIL Open Font License](babysitter/web/assets/OFL-Manrope.txt). The logo and
illustrations were created for this project; see the [brand guide](docs/BRAND.md).

---

<p align="center"><strong>A little oversight. A lot more confidence.</strong></p>

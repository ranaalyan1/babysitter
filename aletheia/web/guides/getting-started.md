# A little setup. A lot of oversight.

Aletheia is a local runtime supervisor for AI coding agents. A final answer is
not enough: successful completion requires independent tests, typechecking and
git-diff evidence.

## 1. Install the runtime

From the Aletheia source checkout, with Python 3.11+ and Git installed:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

The browser console needs no Node runtime or frontend build. Install and
authenticate your coding agent separately using its official instructions.

## 2. Configure the project

In your target git repository (with at least one commit):

```sh
aletheia init --test 'python -m pytest -q' --typecheck 'python -m mypy src'
aletheia doctor --offline
```

Use commands appropriate for that project. If already initialized, edit
`aletheia.json` explicitly; init will not overwrite it. Use a dedicated
worktree. Do not run two agents/supervisors there at once.

## 3. Connect one agent

### Claude Code

```sh
aletheia claude install
aletheia claude status
claude
```

Review installed commands in native `/hooks`, then start a fresh session.
[Claude Code guide](CLAUDE_CODE.md)

### Codex

```sh
aletheia codex install
aletheia codex status
codex
```

Trust the project and review/trust exact native `/hooks` definitions. The installer
does not grant trust, approve permissions or change sandbox settings.
[Codex guide](CODEX.md)

### OpenCode

```sh
aletheia opencode run 'Fix the failing tests'
```

Use the wrapper, not a normal TUI session. Only wrapper exit 0 with `verified:true`
means verified supervision. [OpenCode guide](OPENCODE.md)

## 4. Read the evidence

```sh
aletheia ui
aletheia trace
aletheia trace TASK_ID --metrics
```

Open http://127.0.0.1:8040 on the host machine. The console never runs commands or
changes the worktree. [Console guide](CONSOLE.md)

## Explore before connecting

```sh
aletheia ui --demo
```

The demo is explicitly synthetic. It never reads real repository data and is not
evidence of real model effectiveness.

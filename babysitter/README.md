# Babysitter v0.1 — a local runtime supervisor for AI coding agents

> A model can claim success. Babysitter requires evidence.

Babysitter observes AI coding agents as they work, validates their
actions, verifies their results, and automatically recovers or escalates
when something fails: **Observe → Validate → Repair → Execute → Verify →
Recover → Escalate.**

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Frozen event schema: [`docs/SCHEMA.md`](docs/SCHEMA.md).

## Quick start

```bash
cd babysitter
pip install -r requirements.txt   # fastapi, uvicorn, httpx, pytest

# 1. Run the acceptance demo (weak model → repair → test FAIL → fix →
#    tests PASS → verified_complete, no human in the loop):
./babysitter demo

# 2. Supervise a real project:
cd /path/to/your/project
/path/to/babysitter/babysitter init     # detects test/typecheck commands
/path/to/babysitter/babysitter doctor   # readiness checks
/path/to/babysitter/babysitter start    # protocol server on :8123
```

Point your coding tool at `http://127.0.0.1:8123` as an OpenAI-compatible
(`POST /v1/chat/completions`) or Anthropic-compatible
(`POST /v1/messages`) endpoint. One provider in v0.1: set
`provider.base_url` in `babysitter.json` (default: Ollama's
`http://localhost:11434/v1`) and list ladder models (weak → strong) for
escalation. Inspect anything with:

```bash
./babysitter trace                    # recent tasks
./babysitter trace <task-id>          # full event log
./babysitter trace <task-id> --metrics
./babysitter trace --metrics          # global metrics
```

## Config (`babysitter.json`)

```json
{
  "verify": {
    "test": ["python3", "-m", "pytest", "-q"],
    "typecheck": null,
    "timeout_s": 180
  },
  "provider": {
    "base_url": "http://localhost:11434/v1",
    "api_key_env": "BABYSITTER_API_KEY"
  },
  "ladder": ["qwen2.5-coder:0.5b", "qwen2.5-coder:7b"],
  "escalation_threshold": 2,
  "max_steps": 12,
  "max_attempts_per_step": 3
}
```

## Layout

```text
babysitter/            CLI shim (sets PYTHONPATH, execs the CLI)
requirements.txt       fastapi, uvicorn, httpx, pytest — nothing exotic
src/babysitter/
  schema.py            frozen event/task-state schema v1 + SQLite DDL
  store.py             SQLite store (Observe persistence + schema enforcement)
  toolspec.py          v0.1 minimal toolset (read/write/edit_file + schemas)
  validate.py          Validate stage (+ protocol-mode vs agent schemas)
  repair.py            Repair stage (JSON healing + coerce/defaults)
  execute.py           Execute stage (loop-mode tool runner)
  verify.py            verification engine (real commands + git diff)
  classify.py          failure classification (5 deterministic classes)
  recover.py           checkpoints (git/file-copy), rollback, retry context
  escalate.py          escalation manager (fail-counter rule + ladder)
  provider.py          one OpenAI-compatible client + scripted test doubles
  loop.py              supervised task loop (all seven stages wired)
  server.py            protocol server (/v1/messages, /v1/chat/completions, /v1/models)
  metrics.py           metrics from the event log
  cli.py               init / start / doctor / trace / demo
tests/                 pytest suite (110 tests; hermetic + real-suite runs)
docs/                  ARCHITECTURE.md, SCHEMA.md (frozen)
```

## Testing

```bash
python3 -m pytest tests/ -q
```

The suite mixes hermetic tmp-repo tests with runs against **real**
suites: this monorepo's `@test0/core` vitest suite (pass and
deliberately-broken cases), Babysitter's own pytest files, and —
verified during development — the external `six` library's suite
(184 tests) through the verification engine.

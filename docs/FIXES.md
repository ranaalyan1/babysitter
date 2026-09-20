# Failure fixes — 2026-09-20

The original 61-test suite was green. Targeted regressions reproduced **12 failing
cases** that it did not cover; these were fixed rather than suppressing checks.

| Failure | Fix |
| --- | --- |
| Unknown task caused an exception inside the error handler | Return HTTP 404 with a clean error and `X-Babysitter-Verified: false`; don't look up a nonexistent task twice. |
| Malformed upstream completions or model lists escaped as AttributeError | Check JSON object/choice shapes before accessing fields; raise the normal recoverable `ProviderError`. |
| Tests could run stale Python bytecode after same-size edits | Use a fresh per-command `PYTHONPYCACHEPREFIX` and disable bytecode writes. Existing project `.pyc` caches are not trusted or deleted. |
| Forced tool selection stayed active on every internal turn | Honor it for the first accepted managed batch, then release it for recovery/final completion. |
| Reused model tool IDs broke multi-turn relay continuation | Assign unique IDs when needed; log the repair and use the corrected ID in execution results and client responses. |
| Bad config shapes/unknown fields raised tracebacks; booleans and NaN passed numeric validation | Validate config objects, known fields, types, finite positive limits, strings, environment-variable names, and URL ports; CLI reports a clean configuration error. |

## Working-server evidence

`python scripts/demo.py --http` now tests the installed CLI server as a separate
process with authenticated TCP requests, including `/v1/models` and the completion
endpoint. The process receives a dynamically assigned port and is shut down after
the demo. Both CLI/TCP scenarios are included in the automated test suite.

Observed runs:

| Scenario | Terminal state | Model sequence | Failed verification rounds caught |
| --- | --- | --- | ---: |
| Real HTTP recovery | `verified_complete` | weak → weak → weak | 1 |
| Real HTTP escalation | `verified_complete` | weak → weak → strong → weak | 2 |

The initial failing tests are deliberate fault injection. Neither demo treats a
failed verification as successful completion. The provider is still a scripted
fixture, not an actual weak/free model; these checks establish runtime/server
correctness, not model capability.

Reproduce from the repository root:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
mypy babysitter scripts/demo.py
python scripts/demo.py --http
python scripts/demo.py --http --fail-twice
```

Local traces, reports and CLI server logs are under `.babysitter/demo-*/`.
For real-model tasks, configure a reachable OpenAI-compatible provider and the
project's actual test/typecheck commands using `babysitter init`, then run
`babysitter doctor` before `babysitter start`. No model service is secretly
installed or substituted for a configured provider.

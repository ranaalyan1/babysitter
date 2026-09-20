# Contributing to Babysitter

Small, evidence-backed changes are welcome. Preserve the distinction between
observed agent behavior, independently verified results, and unmeasured claims.

## Local setup

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
mypy babysitter
```

No Node dependency or frontend build is needed to run the console:

```sh
babysitter ui --demo
```

## Before changing the runtime

1. Read `docs/SCHEMA.md`, `docs/ARCHITECTURE.md`, and the relevant adapter contract.
2. Do not change core schema v1 casually. Additive adapter state must be explicit.
3. Never record success solely from model text, native process exit, or a rollback.
4. Preserve checkpoints before safe rollback; never silently discard existing work.
5. Keep permissions, authentication and model choice native to each agent.
6. Add a failing regression first, including negative completion cases.

Real native-client tests are opt-in through `BABYSITTER_CLAUDE_BIN`,
`BABYSITTER_CODEX_BIN`, and `BABYSITTER_OPENCODE_BIN`. They use scripted local
endpoints and isolated homes, not real provider credentials. Never run fault
injection against a working user repository.

## Interface work

Read `docs/INTERFACE_CONTRACT.md` and `docs/BRAND.md`. Keep the console read-only,
separate from the protocol server, and free of tracking/CDN dependencies. Native
payloads are untrusted text; do not interpolate them as HTML. Demo data must stay
clearly labeled. Exercise desktop, narrow screens, keyboard access, empty states,
loading failures, authentication, filters and checkpoint inspection.

The optional browser test harness uses Playwright and axe:

```sh
npm install --prefix tests/browser
npm exec --prefix tests/browser -- playwright install --with-deps chromium
# In another terminal:
babysitter ui --demo
# Then:
node scripts/test_console_browser.mjs
```

Set `BABYSITTER_CONSOLE_URL` to test another local preview URL. A custom Chromium
binary can be selected with `BABYSITTER_BROWSER_EXECUTABLE`; custom shared-library
paths belong in your local environment, not the repository. Browser dependencies
are development-only. Do not commit node_modules or browser downloads.

Console documentation is packaged for offline use. After editing a linked guide,
run `python scripts/sync_console_docs.py`; tests check that the copies match.

## Pull request checklist

- Explain behavior, scope, visibility limits and failure handling.
- Include tests, mypy output, and reproduction commands.
- Run `git diff --check`; keep generated datasets, credentials and trace databases out of Git.
- Update the appropriate guide and changelog; preserve historical validation reports.
- Do not claim real-model effectiveness, complete action visibility or time savings without evidence.

Report security issues privately; see `SECURITY.md`. A project-wide license still
needs a maintainer decision. This guide does not grant additional license rights.

# Your agents, with a safety net

The Babysitter console is a read-only view of local supervision evidence. It is
not an agent launcher, cloud account, model router or execution API.

## Open the console

```sh
babysitter ui
babysitter --root /path/to/project ui
```

Open http://127.0.0.1:8040. No database is a valid empty workspace: the console
will explain how to configure an agent instead of inventing activity. It does
not create a database, run migrations, or take the supervisor's project lock.

```sh
babysitter ui --demo
```

Demo mode serves synthetic, clearly labeled fixtures. It never reads your project
configuration, database, working tree or checkpoints. Demo counts and sample
command output must not be represented as actual verification or model quality.

## What you can do

- **Overview:** inspect recorded task counts, failed check rounds, checkpoint
  counts, and recent recorded events. “In progress” means a stored nonterminal
  state, not a heartbeat or live connection to an agent.
- **Tasks:** search task goals, agent names or IDs; filter by status; open a task.
- **Timeline:** inspect observed event payloads, timestamps, attempts and stages.
- **Verification:** read command output, exit status, duration and timeouts.
- **Checkpoints:** inspect retained manifests and file previews. There is
  deliberately no Restore button; the console cannot modify the worktree.
- **Export trace:** download the loaded task/event/checkpoint metadata as JSON.
  Truncation and demo mode remain explicit in the exported object.
- **Agent integrations:** get copyable setup commands. They are instructions,
  not browser-triggered execution; review native permissions and hook trust.
- **Workspace:** see the configured test/typecheck commands. Density and automatic
  refresh preferences affect this browser only, not `babysitter.json`.

Use Cmd/Ctrl+K or `/` to search pages and tasks. Escape dismisses dialogs. Dialog
focus is contained, controls are keyboard accessible, navigation adapts to narrow
screens, and animations honor reduced-motion preferences.

## Connect the agent outside the browser

First configure real checks in your project:

```sh
babysitter init --test 'python -m pytest -q' --typecheck 'python -m mypy src'
babysitter doctor --offline
```

Use commands meaningful for the actual project, not placeholders such as `true`.
Install the native agent separately through its official mechanism.

- Claude Code: `babysitter claude install`; inspect native `/hooks`.
- Codex: `babysitter codex install`; trust the project and exact native hooks.
- OpenCode: `babysitter opencode run 'Fix the failing tests'`.

The read-only console can coexist with any one of these. Do not run multiple
supervisors or agents in the same worktree.

## Private remote access

The default bind is loopback. For an explicitly authorized private remote console,
set `BABYSITTER_UI_TOKEN` in the host environment, then:

```sh
babysitter ui --host 0.0.0.0 --port 8040
```

Enter that console token in the browser's unlock dialog. It is sent in a Bearer
header and held only in JavaScript memory; a reload clears it. It is never put
in a URL, cookie or localStorage. Configure the secret using your own terminal or
secret manager; do not put it in a repository, screenshots or chat.

Use an HTTPS reverse proxy or a private tunnel for remote access. This app does
not implement TLS, accounts, token rotation or per-user authorization. A valid
console token grants read access to the selected repository's evidence and
retained source. Do not expose it publicly. Static UI assets contain no private
evidence and can load before authentication.

The demo may bind publicly without a token because it serves only synthetic
fixtures. The preview host is accepted. All browser API requests are relative
same-origin URLs; there are no hardcoded localhost browser-service calls.
Cross-origin API requests are rejected; no wildcard CORS is enabled.

## Limits and data handling

- Statistics cover all tasks/checkpoints in the database. The newest 100 tasks
  are listed; the interface labels truncation when more exist.
- A task view loads up to 5,000 events within a 4 MB payload budget. Exports contain
  only loaded events. Use `babysitter trace TASK_ID` for the complete CLI trace.
- A manifest is limited to 2 MB and 1,000 displayed file entries. File previews
  are at most 64 KB; binary content is not rendered as text.
- Inspection only reads canonical retained artifacts below
  `.babysitter/checkpoints`. Arbitrary filesystem paths and symlinked artifacts
  are not served, even if a database manifest path points elsewhere.
- Known credential patterns are redacted, but heuristic redaction cannot detect
  every secret. Treat traces, previews, exports and screenshots as sensitive.
- Refresh runs every 15 seconds when enabled and the page is visible. Task details
  are a snapshot; close/reopen or refresh to inspect newer evidence.
- Configuration detection/history is not proof that native hooks are enabled,
  trusted or currently running. Model routing and escalation remain agent-owned.

The protocol API stays separate on port 8030 and still rejects browser-origin
traffic. Its local token is different from the console token. No new browser
execution routes were added.

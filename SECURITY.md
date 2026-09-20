# Security boundaries

Aletheia executes configured verification commands in runtime modes. Treat the
runtime as a trusted local process with access to the selected worktree—not as an
OS sandbox. Use a dedicated worktree, review native permissions, and avoid
untrusted hooks, plugins, tests and configuration.

## Local console

The v0.4 browser console has a separate, read-only FastAPI app. It never executes
commands, starts agents, restores files, changes task states, runs migrations, or
takes runtime ownership. Real non-loopback API access requires
`ALETHEIA_UI_TOKEN`. Use HTTPS/private tunneling for remote viewing. Authorized
viewers can inspect source evidence; do not expose the console publicly.

The browser keeps the console token only in memory. It is not a GitHub credential
or model key. Cross-origin API requests are rejected. Task strings are escaped,
responses are bounded, and checkpoint reads reject arbitrary paths and symlinks.
Known credential patterns are redacted, but this is not a complete secret scanner.
Inspect traces/screenshots before sharing them.

Demo mode uses synthetic fixtures and never reads project evidence. It is the
only mode suitable for an unauthenticated public presentation preview.

## Protocol and native modes

The protocol execution API remains separate and rejects browser-origin requests.
Non-loopback binding requires `ALETHEIA_LOCAL_TOKEN`, independent of the console
token. Do not expose execution APIs or provider credentials publicly.

Native hooks may be disabled, untrusted, skipped or timed out by their host.
OpenCode's wrapper observes emitted results after execution, not every internal
action. Escaped/detached processes and external effects exceed process-group and
snapshot guarantees. Multi-agent/background operation is not supported.

Ignored/generated files are outside snapshot scope. Configured tests can be
incorrect or malicious; passing them does not prove arbitrary requirements.

## Reporting

Do not disclose credentials, raw private transcripts or exploit details in a
public issue. Use GitHub private vulnerability reporting if enabled, or arrange
a private channel with the repository maintainer first. Do not test vulnerabilities
against other people's agents, credentials, repositories or hosted services.

No external security audit or hard fail-closed guarantee is claimed.

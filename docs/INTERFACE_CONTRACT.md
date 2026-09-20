# Local interface contract (v0.4)

Scope approved by the request for a logo, interface and complete presentation.
This adds a branded, read-only local console—not a cloud dashboard, IDE, agent
launcher, provider manager or multi-agent control plane.

- A separate `babysitter ui` FastAPI app serves packaged, dependency-free browser
  assets. The existing protocol server and its browser-origin rejection stay intact.
- Real mode opens the selected project's existing SQLite database using `mode=ro`
  and `query_only`. It never creates/migrates state, takes runtime ownership,
  executes commands, restores files, or changes task state.
- No database is a valid empty workspace. Demo mode uses explicitly labeled,
  synthetic fixtures and never reads project state or checkpoint files.
- Local hosts work without a token. Real non-loopback serving requires
  `BABYSITTER_UI_TOKEN`. API calls use a Bearer header; the browser keeps the token
  only in memory. Same-origin requests only; no CORS wildcard or URL credentials.
- All task content is untrusted: render escaped text, redact known secret patterns,
  bound responses and checkpoint reads. Never serve arbitrary repository paths.
- Checkpoint inspection resolves only canonical retained manifests/blobs under
  `.babysitter/checkpoints`, rejects symlinks/invalid identifiers, and never restores.
- Counts cover the whole task table. The newest 100 tasks are listed; task events
  are bounded to 5,000 and truncation is explicit. No invented live connectivity,
  token savings, model quality, or proof beyond the configured checks.
- Read-only setup guides supply copyable CLI commands. Agent trust/permissions
  still require native review. DeepSeek and other agents are not advertised as ready.
- Responsive, keyboard accessible, reduced-motion aware; no third-party analytics,
  remote fonts, or browser calls to localhost services.

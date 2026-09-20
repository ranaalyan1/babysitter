"use strict";
const paths = {
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  tasks: "M8 6h12M8 12h12M8 18h12M3 6h.01M3 12h.01M3 18h.01",
  shield: "M12 3 3 7v5c0 5 5 8 9 10 4-2 9-5 9-10V7l-9-4Z M8 12l3 3 5-6",
  layers: "m12 3 10 5-10 5L2 8l10-5Zm-10 10 10 5 10-5M2 18l10 5 10-5",
  plug: "m8 3 0 5m8-5v5M5 8h14v3a7 7 0 0 1-7 7v4M5 11V8",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2",
  folder: "M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v10H3V6Z",
  chevron: "m9 5 7 7-7 7",
  down: "m6 9 6 6 6-6",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  search: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 6 6",
  lock: "M6 10h12v11H6V10Zm2 0V6a4 4 0 0 1 8 0v4",
  book: "M12 5C9 2 4 3 2 4v16c4-2 7-1 10 1 3-2 6-3 10-1V4c-4-2-7-1-10 1Zm0 0v16",
  check: "m5 12 4 4L19 6",
  circlecheck: "M22 11a10 10 0 1 1-6-8M9 11l3 3L22 4",
  refresh: "M20 7A9 9 0 1 0 21 15M20 2v6h-6",
  plus: "M12 5v14M5 12h14",
  code: "m8 5-6 7 6 7m8-14 6 7-6 7",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
  repair: "m14 5 4 4 4-4a7 7 0 0 1-9 9l-8 8-3-3 8-8a7 7 0 0 1 9-9l-5 3Z",
  play: "m7 3 14 9-14 9V3Z",
  recover: "M3 4v6h6M3 10a9 9 0 1 1 0 7",
  escalate: "m6 13 6-6 6 6M12 7v14M4 3h16",
  clock: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 4v6l4 2",
  alert: "m12 3 10 18H2L12 3Zm0 6v5m0 3h.01",
  close: "m6 6 12 12M6 18 18 6",
  external: "M14 3h7v7m0-7L10 14M10 3H3v18h18v-7",
  copy: "M9 9h12v12H9V9ZM5 15H3V3h12v2",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
  terminal: "m4 5 6 6-6 6m9 0h7",
  menu: "M3 5h18M3 12h18M3 19h18",
  file: "M14 2H4v20h16V8l-6-6Zm0 0v6h6M8 13h8M8 17h6",
  spark: "m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3Z",
  git: "M6 3v12a4 4 0 0 0 4 4h5M6 3a2 2 0 1 0 0 .1M18 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4M18 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4M18 7v2a4 4 0 0 1-4 4H6",
};
const icon = (n) =>
  `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[n] || paths.file}"/></svg>`;
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const names = {
  "claude-code": "Claude Code",
  codex: "Codex",
  opencode: "OpenCode",
  protocol: "Protocol",
};
const labels = {
  verified_complete: "Verified",
  recovering: "Recovering",
  failed: "Needs attention",
  verifying: "Verifying",
  verification_unavailable: "Unverified",
  executing: "Executing",
  observed: "Observed",
  awaiting_tools: "Awaiting tools",
  repairing: "Repairing",
  escalating: "Escalating",
  validating: "Validating",
  passed: "Passed",
};
const symbol = (s) =>
  s === "verified_complete" || s === "passed"
    ? "check"
    : s === "failed" || s === "verification_unavailable"
      ? "alert"
      : s === "recovering"
        ? "recover"
        : "clock";
const badge = (s) =>
  `<span class="badge ${esc(Object.hasOwn(labels, s) ? s : "observed")}">${icon(symbol(s))}${esc(labels[s] || s)}</span>`;
const agentIcon = (a) =>
  `<span class="agent-icon ${esc(a)}" aria-hidden="true">${a === "claude-code" ? "✳" : a === "codex" ? "⌘" : a === "opencode" ? "▣" : "⌁"}</span>`;
const agent = (a) =>
  `<span class="agent-chip">${agentIcon(a)}${esc(names[a] || a)}</span>`;
const ago = (s) => {
  const n = Math.max(0, (Date.now() - new Date(s).getTime()) / 60000);
  return !Number.isFinite(n)
    ? "—"
    : n < 1
      ? "just now"
      : n < 60
        ? `${Math.floor(n)}m ago`
        : n < 1440
          ? `${Math.floor(n / 60)}h ago`
          : `${Math.floor(n / 1440)}d ago`;
};
const time = (s) =>
  new Date(s).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
const short = (s) => String(s || "").slice(0, 12);
const lifecycle = [
  ["Observe", "See the action, not the claim.", "eye"],
  ["Validate", "Check inputs and boundaries.", "shield"],
  ["Repair", "Correct what can be corrected.", "repair"],
  ["Execute", "Let the agent do its work.", "play"],
  ["Verify", "Require independent evidence.", "circlecheck"],
  ["Recover", "Roll back. Retry with context.", "recover"],
  ["Escalate", "Ask for help when it matters.", "escalate"],
];
const navs = [
  ["overview", "Overview", "grid"],
  ["tasks", "Tasks", "tasks"],
  ["verification", "Verification", "shield"],
  ["checkpoints", "Checkpoints", "layers"],
  ["agents", "Agent integrations", "plug"],
  ["workspace", "Workspace", "settings"],
];
let data = null,
  route = location.hash.slice(1) || "overview",
  query = "",
  filter = "all",
  token = "",
  currentTask = null,
  currentTab = "timeline",
  requestId = 0,
  modalKind = "",
  lastFocus = null,
  setupAgent = "claude-code",
  errorMessage = "",
  lastRead = null;
let refreshOn = true,
  compact = false;
try {
  refreshOn = localStorage.getItem("bs-refresh") !== "off";
  compact = localStorage.getItem("bs-density") === "compact";
} catch {}
if (!navs.some((n) => n[0] === route)) route = "overview";
const api = async (path) => {
  const r = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (!r.ok) {
    let message = "Could not read the workspace";
    try {
      message = (await r.json()).detail || message;
    } catch {}
    const e = new Error(message);
    e.status = r.status;
    throw e;
  }
  return r.json();
};
function toast(message) {
  const e = document.getElementById("toast");
  e.textContent = message;
  e.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => e.classList.remove("show"), 2800);
}
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    toast(
      ok
        ? "Copied to clipboard"
        : "Clipboard unavailable. Select and copy the command.",
    );
  }
}
function nav(to) {
  if (to === route) {
    render();
    return;
  }
  location.hash = to;
}
window.addEventListener("hashchange", () => {
  route = location.hash.slice(1);
  if (!navs.some((n) => n[0] === route)) route = "overview";
  query = "";
  filter = "all";
  closeModal();
  render();
  window.scrollTo(0, 0);
});
function shell() {
  return `<aside class="sidebar" aria-label="Main navigation"><a class="brand" href="#overview"><img src="/assets/logo.svg" alt="Aletheia logo">aletheia<b>.</b></a><div class="brand-sub">LOCAL SUPERVISION</div><button class="workspace-switch" data-action="workspace-info"><span class="folder">${icon("folder")}</span><span><strong>${esc(data.project)}</strong><small>Local workspace</small></span>${icon("down")}</button><div class="nav-label">WORKSPACE</div><nav>${navs.slice(0, 4).map(navItem).join("")}<div class="nav-label">CONFIGURATION</div>${navs.slice(4).map(navItem).join("")}</nav><div class="sidebar-bottom"><div class="local-note">${icon("shield")}<strong>A little peace of mind.</strong>Your agents build.<br>Aletheia checks the work.</div><div class="sidebar-footer"><button data-action="docs">${icon("book")}Documentation</button><span>v${esc(data.version)}</span></div></div></aside><div class="shell"><header class="topbar"><button class="icon-button mobile-menu" data-action="menu" aria-label="Toggle navigation">${icon("menu")}</button><div class="crumb">${icon("folder")}<span>${esc(data.project)}</span><span class="slash">/</span><b>${esc(navs.find((n) => n[0] === route)?.[1] || "Overview")}</b></div><div class="top-actions"><button class="search-trigger" data-action="search" aria-label="Search workspace">${icon("search")}<span>Search workspace</span><kbd>⌘ K</kbd></button><span class="read-only"><i class="dot"></i>Read-only console</span><span class="avatar" title="Local workspace, no cloud account">al</span></div></header>${data.mode === "demo" ? `<div class="demo-strip"><strong>DEMO</strong><span>You’re exploring sample data. No agents are running and no real repository is connected.</span><button data-action="workspace-info">Connect your workspace ${icon("arrow")}</button></div>` : ""}<main id="main" class="content" tabindex="-1">${mainContent()}</main></div>`;
}
function navItem([id, label, ico]) {
  return `<a class="nav-item ${route === id ? "active" : ""}" href="#${id}" ${route === id ? 'aria-current="page"' : ""}>${icon(ico)}${label}${id === "tasks" ? `<span class="count">${data.stats.total}</span>` : ""}</a>`;
}
function footer() {
  return `<footer class="footer"><span>${icon("lock")}Local-first. Evidence-driven. Always on your side.</span><span>${data.mode === "demo" ? "Illustrative data" : `Last read ${esc(lastRead?.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) || "—")}`}<button data-action="docs">Docs ${icon("external")}</button></span></footer>`;
}
const headings = {
  overview: [
    "Overview",
    "A clear view of the work. And the evidence behind it.",
  ],
  tasks: ["Tasks", "Every task, from first action to verified outcome."],
  verification: [
    "Verification",
    "Independent checks. Not another “looks good to me.”",
  ],
  checkpoints: [
    "Checkpoints",
    "A safety net for every change. Nothing silently discarded.",
  ],
  agents: [
    "Agent integrations",
    "Your favorite coding agents. A little more accountability.",
  ],
  workspace: ["Workspace", "Your local environment, without the guesswork."],
};
function mainContent() {
  const [title, sub] = headings[route];
  return `<div class="page-heading"><div><h1>${title}</h1><p>${sub}</p></div><div class="heading-actions"><button class="btn" data-action="refresh" aria-label="Refresh workspace">${icon("refresh")}<span class="refresh-label">Refresh</span></button><button class="btn primary" data-action="setup">${icon("plus")}Set up an agent</button></div></div>${errorMessage ? `<div class="connection-error" role="alert">${esc(errorMessage)}. Displaying the last loaded snapshot. <button data-action="refresh">Retry</button></div>` : ""}${{ overview: overview, tasks: tasksPage, verification: verificationPage, checkpoints: checkpointsPage, agents: agentsPage, workspace: workspacePage }[route]()}${footer()}`;
}
function render() {
  if (!data) return;
  document.body.classList.toggle("compact", compact);
  document.getElementById("app").innerHTML = shell();
  document.title = `${headings[route][0]} · Aletheia`;
}
function stats() {
  const s = data.stats;
  return `<section class="stats" aria-label="Workspace metrics">${[
    [
      "Verified tasks",
      s.verified,
      `of ${s.total} recorded tasks`,
      "circlecheck",
      "Evidence, not promises",
    ],
    [
      "In progress",
      s.active,
      "Recorded nonterminal states",
      "clock",
      "Not a live connection check",
    ],
    [
      "Failures caught",
      s.caught,
      "Before a successful completion",
      "shield",
      "Failed verification rounds",
    ],
    [
      "Saved checkpoints",
      s.checkpoints,
      "Inspectable, never silently lost",
      "layers",
      "Baseline + unsuccessful changes",
    ],
  ]
    .map(
      ([label, value, sub, ico, title]) =>
        `<article class="stat" title="${esc(title)}"><div class="stat-top"><span>${label}</span><span class="stat-icon">${icon(ico)}</span></div><div class="stat-value"><strong>${value}</strong>${label === "Verified tasks" && s.verified ? "<small>✓ checked</small>" : ""}</div><p>${sub}</p></article>`,
    )
    .join("")}</section>`;
}
function overview() {
  return `<section class="hero"><div class="hero-copy"><div class="eyebrow">${icon("spark")}A SECOND PAIR OF EYES</div><h2>Let your agents build.<br>We’ll watch the details.</h2><p>Every change checked. Every recovery traceable.<br>Nothing marked done without evidence.</p><button class="text-button" data-action="workflow">Meet your safety net ${icon("arrow")}</button></div><img class="hero-art" src="/assets/oversight.svg" alt="Aletheia checks agent actions before they become verified results"></section>${stats()}<div class="workspace-grid"><div><section class="panel"><div class="panel-head"><h2>Recent tasks <span class="tag">${data.stats.total}</span></h2><button class="text-button" data-nav="tasks">View all tasks ${icon("arrow")}</button></div><div class="filter-row"><div class="tabs" aria-label="Filter recent tasks"><button class="${filter === "all" ? "selected" : ""}" data-filter="all" aria-pressed="${filter === "all"}">All tasks</button><button class="${filter === "attention" ? "selected" : ""}" data-filter="attention" aria-pressed="${filter === "attention"}">Needs attention</button></div><span class="subtle"><small>Latest activity</small></span></div><div id="task-table">${taskTable(true)}</div></section><section class="panel activity"><div class="panel-head"><h2>Recent activity</h2><span class="tag">${data.mode === "demo" ? "SAMPLE EVENTS" : "RECORDED EVENTS"}</span></div>${activityList()}</section></div>${workflowPanel()}</div>`;
}
function workflowPanel() {
  return `<aside class="panel workflow"><div class="panel-head"><h2>The supervision loop</h2>${icon("recover")}</div><div class="workflow-list">${lifecycle.map(([name, sub, ico]) => `<div class="workflow-step ${name === "Verify" ? "focus" : ""}"><span class="workflow-node">${icon(ico)}</span><div><h3>${name}</h3><p>${sub}</p></div>${name === "Verify" ? '<span class="tag">THE NON-NEGOTIABLE</span>' : ""}</div>`).join("")}</div><div class="workflow-foot">${icon("lock")}Passing checks is required.<br>Agent confidence is not evidence.</div></aside>`;
}
function visibleTasks() {
  return data.tasks.filter(
    (t) =>
      (!query ||
        `${t.goal} ${t.id} ${names[t.adapter] || t.adapter}`
          .toLowerCase()
          .includes(query.toLowerCase())) &&
      (filter === "all" ||
        (filter === "attention" &&
          ["failed", "recovering", "verification_unavailable"].includes(
            t.state,
          )) ||
        t.state === filter),
  );
}
function taskTable(recent = false) {
  const all = visibleTasks(),
    rows = recent ? all.slice(0, 5) : all;
  if (!rows.length)
    return empty(
      data.tasks.length ? "No matching tasks" : "Your first task starts here",
      data.tasks.length
        ? "Try another search or clear the filters."
        : "Connect an agent from your terminal. Verified work will appear here automatically.",
      data.tasks.length ? "clear-filters" : "setup",
      data.tasks.length ? "Clear filters" : "Set up an agent",
    );
  return `<div class="table-wrap" tabindex="0" role="region" aria-label="Scrollable evidence table"><table><thead><tr><th>Task</th><th>Agent</th><th>Status</th>${recent ? "" : "<th>Attempts</th>"}<th>Updated</th><th><span class="sr-only">Open task</span></th></tr></thead><tbody>${rows.map((t) => `<tr class="task-row" data-task="${esc(t.id)}"><td><button class="task-title" data-task="${esc(t.id)}"><span class="status-symbol ${esc(t.state)}">${icon(symbol(t.state))}</span><span><strong title="${esc(t.goal)}">${esc(t.goal)}</strong><small class="mono">${esc(short(t.id))}</small></span></button></td><td>${agent(t.adapter)}</td><td>${badge(t.state)}</td>${recent ? "" : `<td>${esc(t.attempts)}</td>`}<td><small title="${esc(t.updated_at)}">${esc(ago(t.updated_at))}</small></td><td>${icon("chevron")}</td></tr>`).join("")}</tbody></table></div><div class="table-foot"><span>Showing ${rows.length} of ${all.length} ${data.tasks_truncated ? "loaded " : ""}tasks${data.tasks_truncated ? " · newest 100 loaded" : ""}</span><span>${icon("lock")} Completion requires evidence</span></div>`;
}
function empty(title, description, action, label) {
  return `<div class="empty">${icon("layers")}<h3>${esc(title)}</h3><p>${esc(description)}</p>${action ? `<button class="btn" data-action="${action}">${esc(label)}</button>` : ""}</div>`;
}
function activityInfo(e) {
  const p = e.payload;
  switch (e.kind) {
    case "task.finished":
      return [
        p.state === "verified_complete"
          ? "Task independently verified"
          : "Task ended without verification",
        p.reason || "Test, typecheck, and git-diff evidence recorded.",
        p.state === "verified_complete" ? "circlecheck" : "alert",
      ];
    case "verification.result":
      return [
        p.status === "passed"
          ? "Verification checks passed"
          : "Verification caught a failure",
        p.reason || "Independent command results are available.",
        "shield",
      ];
    case "rollback.completed":
      return [
        "Worktree safely rolled back",
        "Unsuccessful changes remain in a retained checkpoint.",
        "recover",
      ];
    case "retry.scheduled":
      return [
        "Recovery attempt scheduled",
        "The agent received failure context, not a false success.",
        "refresh",
      ];
    case "checkpoint.created":
      return [
        "Checkpoint preserved",
        p.purpose === "baseline"
          ? "Original worktree captured."
          : "Unsuccessful contents retained for inspection.",
        "layers",
      ];
    default:
      return [
        "Failure recorded",
        "Inspect the task timeline for evidence.",
        "alert",
      ];
  }
}
function activityList() {
  if (!data.activity.length)
    return empty(
      "Nothing to report. Yet.",
      "Recorded verification and recovery events will show up here.",
    );
  return `<div class="activity-list">${data.activity
    .slice(0, 4)
    .map((e) => {
      const [title, sub, ico] = activityInfo(e);
      return `<button class="activity-item" data-task="${esc(e.task_id)}"><span class="activity-dot">${icon(ico)}</span><span class="activity-text"><strong>${title}</strong><p>${esc(sub)}</p></span><time>${ago(e.timestamp)}</time></button>`;
    })
    .join("")}</div>`;
}
function tasksPage() {
  return `<div class="task-tools"><label class="search-field">${icon("search")}<input id="task-search" type="search" placeholder="Search tasks, agents, or IDs…" value="${esc(query)}" aria-label="Search tasks"></label><select id="status-filter" aria-label="Filter task status">${[
    ["all", "All statuses"],
    ["verified_complete", "Verified"],
    ["attention", "Needs attention"],
    ["verifying", "Verifying"],
    ["recovering", "Recovering"],
  ]
    .map(
      ([s, t]) =>
        `<option value="${s}" ${filter === s ? "selected" : ""}>${t}</option>`,
    )
    .join(
      "",
    )}</select><span class="subtle"><small>${data.stats.total} recorded tasks</small></span></div><section class="panel" id="task-table">${taskTable()}</section>`;
}
function verificationPage() {
  const tasks = data.tasks.filter((t) => t.last_verification);
  return `${stats()}<section class="panel"><div class="panel-head"><h2>Latest evidence per task</h2><span class="tag">TEST + TYPECHECK + GIT-DIFF</span></div><div class="settings-list">${tasks.length ? tasks.map((t) => `<article class="check-card"><header><h3>${esc(t.goal)}</h3>${badge(t.state)}</header><p>${esc(names[t.adapter] || t.adapter)} · ${t.verification_count} recorded verification round${t.verification_count === 1 ? "" : "s"}</p><div class="evidence-chips">${(t.last_verification.commands || []).map((c) => `<span class="badge ${c.exit_code === 0 && !c.timed_out ? "passed" : "failed"}">${icon(c.exit_code === 0 && !c.timed_out ? "check" : "close")}${esc(c.name)}</span>`).join(" ")}</div><button class="text-button" data-task="${esc(t.id)}" data-tab="evidence">Inspect command evidence ${icon("arrow")}</button></article>`).join("") : empty("No verification evidence yet", "A task is never verified from an agent’s answer alone. Configure meaningful tests and typechecks.", "setup", "Configure supervision")}</div></section>`;
}
function checkpointsPage() {
  const tasks = data.tasks.filter((t) => t.checkpoint_count);
  return `<div class="notice">${icon("lock")}<span><strong>Inspect, don’t overwrite.</strong> This console only reads retained checkpoints. It never restores files or resets your worktree.</span></div><section class="panel"><div class="panel-head"><h2>Retained task snapshots</h2><span class="tag">${data.stats.checkpoints} CHECKPOINTS TOTAL</span></div>${tasks.length ? `<div class="table-wrap" tabindex="0" role="region" aria-label="Scrollable evidence table"><table><thead><tr><th>Task</th><th>Agent</th><th>Checkpoints</th><th>Task state</th><th></th></tr></thead><tbody>${tasks.map((t) => `<tr><td><button class="task-title" data-task="${esc(t.id)}" data-tab="checkpoints"><span class="status-symbol">${icon("layers")}</span><span><strong>${esc(t.goal)}</strong><small class="mono">${esc(short(t.id))}</small></span></button></td><td>${agent(t.adapter)}</td><td>${t.checkpoint_count} retained</td><td>${badge(t.state)}</td><td><button class="text-button" data-task="${esc(t.id)}" data-tab="checkpoints">Inspect ${icon("arrow")}</button></td></tr>`).join("")}</tbody></table></div>` : empty("Your safety net is ready", "Task baselines and unsuccessful changes will appear here. No snapshot is created by this console.", "setup", "Set up an agent")}</section>`;
}
function agentsPage() {
  return `<div class="page-grid">${data.agents.map((a) => `<article class="panel agent-card">${agentIcon(a.id)}<h2>${esc(a.name)}</h2><span class="tag">${esc(a.kind)}</span><p>${esc(a.description)}</p><span class="muted-chip">${data.mode === "demo" ? "Demo configuration" : a.observed ? "Observed in loaded task history" : "Not observed in loaded history"}</span><br><button class="btn" data-agent="${esc(a.id)}">Setup instructions ${icon("arrow")}</button></article>`).join("")}</div><div class="notice">${icon("shield")}<span><strong>One agent. One worktree. Native permissions.</strong><br>The console doesn’t launch agents, grant trust, approve tools, or switch models. Use the setup commands in your own terminal.</span></div><section class="panel"><div class="panel-head"><h2>Honest about what’s supported</h2></div><div class="settings-list"><div class="setting"><span>Claude Code & Codex</span><strong>Native hook visibility + Stop verification</strong></div><div class="setting"><span>OpenCode</span><strong>Owned CLI process + post-execution checks</strong></div><div class="setting"><span>DeepSeek & additional agents</span><strong>Not implemented · scope deferred</strong></div></div></section>`;
}
function commandBlock(command) {
  return `<div class="command-block"><button data-copy="${esc(command)}" aria-label="Copy command">${icon("copy")}</button><pre>${esc(command)}</pre></div>`;
}
function workspacePage() {
  const config = data.config;
  return `<div class="settings-grid"><section class="panel"><div class="panel-head"><h2>Project environment</h2><span class="tag">READ-ONLY</span></div><div class="settings-list"><div class="setting"><span>Workspace</span><strong>${esc(data.project)}</strong></div><div class="setting"><span>Location</span><strong class="mono">${esc(data.root)}</strong></div><div class="setting"><span>Runtime version</span><strong>${esc(data.version)}</strong></div><div class="setting"><span>Evidence source</span><strong>${data.mode === "demo" ? "Synthetic demo fixtures" : "Local SQLite · read-only connection"}</strong></div><div class="setting"><span>Configuration</span><strong>${config.error ? "Needs inspection" : config.initialized ? "aletheia.json detected" : "Not initialized"}</strong></div>${config.error ? `<p class="connection-error">${esc(config.error)}</p>` : ""}<div class="command-label">Tests</div>${commandBlock((config.commands.test || []).join(" ") || "# No test command configured")}<div class="command-label">Typecheck</div>${commandBlock((config.commands.typecheck || []).join(" ") || "# No typecheck command configured")}</div></section><div><section class="panel"><div class="panel-head"><h2>Console preferences</h2></div><div class="settings-list"><div class="setting"><span>Refresh evidence every 15s</span><select id="refresh-setting" aria-label="Automatic refresh"><option value="on" ${refreshOn ? "selected" : ""}>On</option><option value="off" ${!refreshOn ? "selected" : ""}>Off</option></select></div><div class="setting"><span>Interface density</span><select id="density-setting" aria-label="Interface density"><option value="comfortable" ${!compact ? "selected" : ""}>Comfortable</option><option value="compact" ${compact ? "selected" : ""}>Compact</option></select></div><p class="subtle"><small>These preferences stay in this browser. They do not change your runtime configuration.</small></p></div></section><div class="notice">${icon("lock")}<span>No accounts. No analytics. No cloud sync. Evidence stays on the machine hosting this console. Keep real remote access private and token-protected.</span></div><button class="text-button" data-action="workspace-info">Open another repository ${icon("arrow")}</button></div></div>`;
}
async function load(manual = false) {
  try {
    const result = await api("/api/workspace");
    data = result;
    lastRead = new Date();
    errorMessage = "";
    if (!modalKind && !document.querySelector("#task-search:focus")) render();
    if (manual) toast("Workspace evidence refreshed");
  } catch (e) {
    if (e.status === 401) {
      authModal();
      return;
    }
    if (data) {
      errorMessage = e.message;
      if (!modalKind) render();
    } else {
      document.getElementById("app").innerHTML =
        `<div class="boot"><img src="/assets/logo.svg" width="56" height="56" alt=""><h1>Let’s reconnect.</h1><p>${esc(e.message)}</p><button class="btn primary" data-action="refresh">Try again</button></div>`;
    }
  }
}
function showModal(html, kind, drawer = false) {
  requestId++;
  lastFocus = lastFocus || document.activeElement;
  modalKind = kind;
  document.getElementById("app").inert = true;
  document.getElementById("overlay").innerHTML =
    `<div class="modal-shade ${drawer ? "drawer-shade" : ""}" data-backdrop><section class="${drawer ? "drawer" : "modal"} ${kind === "search" ? "palette" : ""}" role="dialog" aria-modal="true" aria-labelledby="dialog-title">${html}</section></div>`;
  document.body.classList.add("modal-open");
  requestAnimationFrame(() =>
    document.querySelector("#overlay input, #overlay button")?.focus(),
  );
}
function closeModal() {
  const locked = modalKind === "auth" && !data;
  requestId++;
  document.getElementById("overlay").innerHTML = "";
  document.getElementById("app").inert = false;
  document.body.classList.remove("modal-open");
  modalKind = "";
  currentTask = null;
  const f = lastFocus;
  lastFocus = null;
  if (f?.isConnected) f.focus();
  if (locked)
    document.getElementById("app").innerHTML =
      `<div class="boot"><img src="/assets/logo.svg" width="56" height="56" alt=""><h1>Your console is locked.</h1><p>A local access token is required to read project evidence.</p><button class="btn primary" data-action="unlock">Unlock console</button></div>`;
}
function modalHeader(title, sub = "") {
  return `<header class="modal-header"><div><h2 id="dialog-title">${esc(title)}</h2>${sub ? `<p>${esc(sub)}</p>` : ""}</div><button class="icon-button" data-action="close" aria-label="Close dialog">${icon("close")}</button></header>`;
}
function setup(id = setupAgent) {
  setupAgent = id;
  const a = data.agents.find((a) => a.id === id);
  showModal(
    `${modalHeader("A little setup. A lot of oversight.", "Run these commands in your dedicated project worktree.")}<div class="modal-body"><div class="tabs">${data.agents.map((x) => `<button data-agent="${x.id}" class="${x.id === id ? "selected" : ""}">${x.name}</button>`).join("")}</div><div class="numbered"><span>1</span>Configure meaningful verification</div>${commandBlock("aletheia init --test 'python -m pytest -q' \\\n  --typecheck 'python -m mypy src'")}<p>Already initialized? Edit <code>aletheia.json</code> explicitly. Use the test and typecheck commands that actually cover your project.</p><div class="numbered"><span>2</span>Connect ${a.name}</div>${commandBlock(a.command)}<div class="notice">${icon("shield")}<span>${esc(a.note)}</span></div><div class="numbered"><span>3</span>See the evidence</div>${commandBlock("aletheia ui")}<p>Open the printed local URL. This console reads evidence; it does not execute these commands.</p></div>`,
    "setup",
  );
}
function workspaceInfo() {
  showModal(
    `${modalHeader("Your workspace. Your machine.")}<div class="modal-body"><p>${data.mode === "demo" ? "This is an interactive demo with illustrative tasks and checkpoints. It does not read or modify any repository." : "This console is connected to one project and never takes runtime ownership."}</p><h3>Open your own repository</h3><p>Run this in a terminal on the machine with Aletheia installed:</p>${commandBlock("aletheia --root /path/to/your/repo ui")}<p>The default address is <code>http://127.0.0.1:8040</code>. Native agents and the console can run together; only the console is read-only.</p><div class="notice">${icon("lock")}<span>Real non-loopback access requires <code>ALETHEIA_UI_TOKEN</code>. Never expose project evidence publicly. Token entry is held in browser memory only.</span></div></div>`,
    "workspace-info",
  );
}
const guides = [
  ["getting-started", "Getting started", "book", "GETTING_STARTED.md"],
  ["console", "Using the local console", "grid", "CONSOLE.md"],
  ["claude-code", "Claude Code integration", "plug", "CLAUDE_CODE.md"],
  ["codex", "Codex integration", "terminal", "CODEX.md"],
  ["opencode", "OpenCode integration", "code", "OPENCODE.md"],
  ["validation", "Measured results & limitations", "shield", "VALIDATION.md"],
  ["brand", "Brand & design system", "spark", "BRAND.md"],
];
function docs() {
  showModal(
    `${modalHeader("A field guide to Aletheia.", "Packaged with your console. Available offline.")}<div class="modal-body"><div class="help-grid">${guides.map(([slug, name, ico]) => `<button class="help-link" data-guide="${slug}">${icon(ico)}${name}${icon("arrow")}</button>`).join("")}</div><p>No network requests to external documentation services. These guides ship with the installed runtime.</p><button class="text-button" data-action="workflow">See the supervision loop ${icon("arrow")}</button></div>`,
    "docs",
  );
}
function inlineMarkdown(text) {
  return esc(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
      const local = guides.find((g) => url.split("/").at(-1) === g[3]);
      if (local)
        return `<button class="text-button" data-guide="${local[0]}">${label}</button>`;
      if (/^https:\/\//.test(url))
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`;
      return label;
    });
}
function markdown(text) {
  let html = "",
    code = null,
    para = [],
    list = false;
  const flush = () => {
    if (para.length) {
      html += `<p>${inlineMarkdown(para.join(" "))}</p>`;
      para = [];
    }
    if (list) {
      html += "</ul>";
      list = false;
    }
  };
  for (const line of text.split("\n")) {
    if (line.startsWith("```")) {
      flush();
      if (code !== null) {
        html += `<pre>${esc(code.join("\n"))}</pre>`;
        code = null;
      } else code = [];
      continue;
    }
    if (code !== null) {
      code.push(line);
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = line.match(/^(#{1,4}) (.+)/);
    if (heading) {
      flush();
      html += `<h3>${inlineMarkdown(heading[2])}</h3>`;
      continue;
    }
    if (line.startsWith("- ")) {
      if (para.length) flush();
      if (!list) {
        html += "<ul>";
        list = true;
      }
      html += `<li>${inlineMarkdown(line.slice(2))}</li>`;
      continue;
    }
    if (line.startsWith("|")) {
      flush();
      html += `<p class="mono">${inlineMarkdown(line)}</p>`;
      continue;
    }
    if (list) {
      html += "</ul>";
      list = false;
    }
    para.push(line);
  }
  flush();
  if (code !== null) html += `<pre>${esc(code.join("\n"))}</pre>`;
  return html;
}
async function openGuide(slug) {
  const guide = guides.find((g) => g[0] === slug);
  if (!guide) return;
  showModal(
    `${modalHeader(guide[1])}<div class="loading-line">Opening offline guide…</div>`,
    "guide",
  );
  const rid = requestId;
  try {
    const r = await fetch("/guides/" + slug + ".md");
    if (!r.ok)
      throw new Error("This guide is missing from the installed package");
    const text = await r.text();
    if (rid !== requestId) return;
    showModal(
      `${modalHeader(guide[1], "Offline documentation · shipped with this version")}<div class="modal-body"><button class="text-button" data-action="docs">← All guides</button><article class="guide">${markdown(text)}</article></div>`,
      "guide",
    );
  } catch (e) {
    if (rid !== requestId) return;
    showModal(
      `${modalHeader("Guide unavailable")}<div class="modal-body"><p>${esc(e.message)}</p><button class="btn" data-action="docs">All guides</button></div>`,
      "guide",
    );
  }
}
function workflow() {
  showModal(
    `${modalHeader("A safety net, not another agent.")}<div class="modal-body"><p>Aletheia sits around the work your agent already does. Its non-negotiable: independently verify before recording successful completion.</p><div class="workflow-list">${lifecycle.map(([name, sub, ico]) => `<div class="workflow-step ${name === "Verify" ? "focus" : ""}"><span class="workflow-node">${icon(ico)}</span><div><h3>${name}</h3><p>${sub}</p></div></div>`).join("")}</div><div class="notice">${icon("alert")}<span>Capabilities differ by adapter. Hooks are guardrails, not a hard security sandbox. Passing checks proves those checks—not every intended requirement.</span></div></div>`,
    "workflow",
  );
}
function authModal(message = "") {
  showModal(
    `${modalHeader("Unlock your local console.")}<form id="auth-form" class="modal-body"><p>Enter the <code>ALETHEIA_UI_TOKEN</code> configured on this console’s host. This is not a GitHub or model-provider credential.</p><label for="ui-token">Console access token</label><input id="ui-token" type="password" autocomplete="off" required>${message ? `<p role="alert">${esc(message)}</p>` : ""}<button class="btn primary" type="submit">Unlock console ${icon("arrow")}</button><p>Held in memory only. Reloading clears the token.</p></form>`,
    "auth",
  );
}
async function openTask(id, tab = "timeline") {
  currentTab = tab;
  showModal(
    `${modalHeader("Loading task evidence…")}<div class="loading-line">Reading retained events and checkpoints.</div>`,
    "task",
    true,
  );
  const rid = requestId;
  try {
    const task = await api("/api/tasks/" + encodeURIComponent(id));
    if (rid !== requestId) return;
    currentTask = task;
    drawTask();
  } catch (e) {
    if (rid !== requestId) return;
    showModal(
      `${modalHeader("Evidence unavailable")}<div class="modal-body"><p>${esc(e.message)}</p><button class="btn" data-task="${esc(id)}">Try again</button></div>`,
      "task",
      true,
    );
  }
}
function drawTask() {
  const t = currentTask.task;
  showModal(
    `${modalHeader(t.goal, `${short(t.id)} · recorded task`)}<div class="drawer-meta">${badge(t.state)}${agent(t.adapter)}<span>${esc(t.attempts)} attempt${t.attempts === 1 ? "" : "s"}</span><button class="text-button" data-action="export">${icon("download")}Export trace</button></div><div class="drawer-tabs" role="tablist" aria-label="Task evidence">${[
      ["timeline", "Timeline"],
      ["evidence", "Verification"],
      ["checkpoints", "Checkpoints"],
    ]
      .map(
        ([id, label]) =>
          `<button role="tab" aria-selected="${currentTab === id}" class="${currentTab === id ? "selected" : ""}" data-task-tab="${id}">${label}${id === "checkpoints" ? ` (${currentTask.checkpoints.length})` : ""}</button>`,
      )
      .join(
        "",
      )}</div><div class="drawer-body" role="tabpanel">${currentTask.events_truncated ? '<div class="notice">This event window is truncated (5,000 events / 4 MB maximum). Export is limited to loaded events; use the CLI for a complete trace.</div>' : ""}${currentTab === "timeline" ? timeline() : currentTab === "evidence" ? evidence() : checkpointCards()}</div>`,
    "task",
    true,
  );
}
function timeline() {
  return currentTask.events.length
    ? currentTask.events
        .map(
          (e) =>
            `<article class="timeline-item"><span class="timeline-icon">${icon(lifecycle.find((l) => l[0].toLowerCase() === e.stage)?.[2] || "file")}</span><h3>${esc(e.kind.split(".").join(" · "))}</h3><time>${esc(time(e.timestamp))} · ${esc(e.stage)} · attempt ${esc(e.attempt)}</time><details><summary>Inspect recorded payload</summary><pre>${esc(JSON.stringify(e.payload, null, 2))}</pre></details></article>`,
        )
        .join("")
    : empty(
        "No recorded events",
        "This task has no event evidence to inspect.",
      );
}
function evidence() {
  const checks = currentTask.events.filter(
    (e) => e.kind === "verification.result",
  );
  return checks.length
    ? checks
        .map(
          (e, i) =>
            `<div class="list-header">Round ${i + 1} · ${time(e.timestamp)} ${badge(e.payload.status)}</div>${e.payload.reason ? `<div class="notice">${icon("alert")}<span>${esc(e.payload.reason)}</span></div>` : ""}${(e.payload.commands || []).map((c) => `<article class="check-card"><header><h3>${esc(c.name)}</h3>${badge(c.exit_code === 0 && !c.timed_out ? "passed" : "failed")}</header><p class="mono">${esc((c.argv || []).join(" "))}</p><p>Exit ${esc(c.exit_code ?? "unavailable")} · ${Number(c.duration_seconds || 0).toFixed(2)}s ${c.timed_out ? "· timed out" : ""}${c.output_truncated ? " · output truncated" : ""}</p><details><summary>Command output</summary><pre>${esc((c.stdout || "") + (c.stderr || "") || "No output. Exit status recorded above.")}</pre></details></article>`).join("")}`,
        )
        .join("")
    : empty(
        "Not verified yet",
        "No independent verification result has been recorded. An agent’s final answer is not completion evidence.",
      );
}
function checkpointCards() {
  return currentTask.checkpoints.length
    ? currentTask.checkpoints
        .map(
          (cp) =>
            `<article class="check-card"><header><h3>${cp.purpose === "baseline" ? "Original baseline" : "Unsuccessful changes"}</h3><span class="tag">RETAINED</span></header><p class="mono">${esc(cp.id)}</p><p>${esc(new Date(cp.created_at).toLocaleString())}</p><button class="text-button" data-checkpoint="${esc(cp.id)}">${icon("layers")}Inspect retained files ${icon("arrow")}</button><div class="checkpoint-files" id="cp-${esc(cp.id)}"></div></article>`,
        )
        .join("")
    : empty(
        "No checkpoints recorded",
        "No files can be restored or inspected without retained evidence.",
      );
}
async function inspectCheckpoint(id, filename) {
  const task = currentTask?.task.id;
  if (!task) return;
  const container = document.getElementById("cp-" + id);
  try {
    const result = await api(
      `/api/tasks/${encodeURIComponent(task)}/checkpoints/${encodeURIComponent(id)}${filename ? "?file=" + encodeURIComponent(filename) : ""}`,
    );
    if (currentTask?.task.id !== task || !container?.isConnected) return;
    container.innerHTML = `${result.truncated ? '<p class="subtle">First 1,000 files shown.</p>' : ""}${result.files.map((f) => `<button class="file-row" data-checkpoint="${esc(id)}" data-file="${esc(f.path)}">${icon("file")}<span class="wide-path">${esc(f.path)}</span><code>${esc(f.sha256.slice(0, 10))}</code></button>`).join("")}${result.preview !== undefined ? `<div class="file-preview"><div class="command-label">${esc(filename)} · retained contents</div><pre>${esc(result.preview)}</pre>${result.preview_truncated ? "<p>Preview truncated to 64 KB.</p>" : ""}</div>` : ""}`;
  } catch (e) {
    if (container?.isConnected) container.textContent = e.message;
  }
}
function exportTrace() {
  if (!currentTask) return;
  const blob = new Blob(
    [JSON.stringify({ mode: data.mode, ...currentTask }, null, 2)],
    { type: "application/json" },
  );
  const a = document.createElement("a");
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = `aletheia-${currentTask.task.id}-trace.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Loaded trace exported");
}
function searchModal() {
  showModal(
    `<header class="search-field">${icon("search")}<input id="palette-search" placeholder="Jump to a page or find a task…" aria-label="Search pages and tasks"><button class="icon-button" data-action="close" aria-label="Close search">${icon("close")}</button></header><h2 id="dialog-title" class="sr-only">Search workspace</h2><div id="palette-results" class="palette-list">${searchResults("")}</div>`,
    "search",
  );
}
function searchResults(q) {
  q = q.toLowerCase();
  const pages = navs.filter((n) => n[1].toLowerCase().includes(q));
  const tasks = data.tasks
    .filter((t) => `${t.goal} ${t.id}`.toLowerCase().includes(q))
    .slice(0, 7);
  return (
    pages
      .map(
        ([id, label, ico]) =>
          `<button data-nav="${id}">${icon(ico)}${label}<small>PAGE</small></button>`,
      )
      .join("") +
      tasks
        .map(
          (t) =>
            `<button data-task="${esc(t.id)}">${icon(symbol(t.state))}${esc(t.goal)}<small>${esc(short(t.id))}</small></button>`,
        )
        .join("") || '<p class="loading-line">No matching pages or tasks.</p>'
  );
}
document.addEventListener("click", (e) => {
  const t = e.target.closest("button,a[data-nav],tr[data-task]");
  if (e.target.matches("[data-backdrop]")) {
    closeModal();
    return;
  }
  if (!t) return;
  if (t.dataset.nav) {
    closeModal();
    nav(t.dataset.nav);
    return;
  }
  if (t.dataset.task) {
    openTask(t.dataset.task, t.dataset.tab || "timeline");
    return;
  }
  if (t.dataset.agent) {
    setup(t.dataset.agent);
    return;
  }
  if (t.dataset.guide) {
    openGuide(t.dataset.guide);
    return;
  }
  if (t.dataset.copy) {
    copy(t.dataset.copy);
    return;
  }
  if (t.dataset.filter) {
    filter = t.dataset.filter;
    render();
    return;
  }
  if (t.dataset.taskTab) {
    currentTab = t.dataset.taskTab;
    drawTask();
    return;
  }
  if (t.dataset.checkpoint) {
    inspectCheckpoint(t.dataset.checkpoint, t.dataset.file);
    return;
  }
  const a = t.dataset.action;
  if (a === "setup") setup();
  else if (a === "close") closeModal();
  else if (a === "unlock") authModal();
  else if (a === "refresh") load(true);
  else if (a === "workspace-info") workspaceInfo();
  else if (a === "docs") docs();
  else if (a === "workflow") workflow();
  else if (a === "search") searchModal();
  else if (a === "menu")
    document.querySelector(".sidebar")?.classList.toggle("open");
  else if (a === "export") exportTrace();
  else if (a === "clear-filters") {
    query = "";
    filter = "all";
    render();
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "task-search") {
    query = e.target.value;
    document.getElementById("task-table").innerHTML = taskTable();
  }
  if (e.target.id === "palette-search")
    document.getElementById("palette-results").innerHTML = searchResults(
      e.target.value,
    );
});
document.addEventListener("change", (e) => {
  if (e.target.id === "status-filter") {
    filter = e.target.value;
    document.getElementById("task-table").innerHTML = taskTable();
  }
  if (e.target.id === "refresh-setting") {
    refreshOn = e.target.value === "on";
    try {
      localStorage.setItem("bs-refresh", refreshOn ? "on" : "off");
    } catch {}
    toast("Refresh preference saved");
  }
  if (e.target.id === "density-setting") {
    compact = e.target.value === "compact";
    try {
      localStorage.setItem("bs-density", e.target.value);
    } catch {}
    document.body.classList.toggle("compact", compact);
    toast("Density preference saved");
  }
});
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "auth-form") return;
  e.preventDefault();
  token = document.getElementById("ui-token").value;
  try {
    data = await api("/api/workspace");
    lastRead = new Date();
    closeModal();
    render();
  } catch (err) {
    token = "";
    authModal(err.message);
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (modalKind) closeModal();
    else document.querySelector(".sidebar")?.classList.remove("open");
  }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k" && data) {
    e.preventDefault();
    searchModal();
  }
  if (
    e.key === "/" &&
    !modalKind &&
    data &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)
  ) {
    e.preventDefault();
    searchModal();
  }
  if (e.key === "Tab" && modalKind) {
    const list = [
      ...document.querySelectorAll(
        "#overlay button,#overlay a[href],#overlay input,#overlay select,#overlay summary",
      ),
    ].filter((x) => !x.disabled && x.getClientRects().length);
    const first = list[0],
      last = list.at(-1);
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last?.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first?.focus();
    }
  }
});
setInterval(() => {
  if (
    data &&
    refreshOn &&
    !document.hidden &&
    !modalKind &&
    !document.querySelector("input:focus,select:focus")
  )
    load();
}, 15000);
load();

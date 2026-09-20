/** Optional browser integration + accessibility checks against a running demo. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(
  new URL("../tests/browser/package.json", import.meta.url),
);
const { chromium } = require("playwright");
const { default: AxeBuilder } = require("@axe-core/playwright");
const executablePath = process.env.BABYSITTER_BROWSER_EXECUTABLE;
const browser = await chromium.launch({
  headless: true,
  ...(executablePath
    ? {
        executablePath,
        args: [
          "--no-sandbox",
          "--disable-dev-shm-usage",
          "--no-zygote",
          "--use-gl=angle",
          "--use-angle=swiftshader",
          "--enable-unsafe-swiftshader",
        ],
      }
    : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  acceptDownloads: true,
});
const page = await context.newPage();
const base = process.env.BABYSITTER_CONSOLE_URL || "http://127.0.0.1:8040";
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const reports = [];
async function audit(name) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  reports.push({
    page: name,
    violations: violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({ target: n.target, why: n.failureSummary })),
    })),
  });
}
try {
  await page.goto(base);
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  assert.ok(
    await page.locator(".demo-strip").isVisible(),
    "Run this harness against --demo, not private evidence",
  );
  await audit("overview");
  await page
    .getByRole("button", { name: "Handle expired session tokens" })
    .click();
  await page.getByRole("tab", { name: "Verification", exact: true }).click();
  await page.getByText("Round 1", { exact: false }).waitFor();
  await audit("task evidence");
  await page.getByRole("tab", { name: "Checkpoints (2)" }).click();
  await page
    .getByRole("button", { name: "Inspect retained files" })
    .first()
    .click();
  await page
    .getByRole("button", { name: /src\/runtime.py/ })
    .first()
    .click();
  await page
    .getByText("Illustrative checkpoint content", { exact: false })
    .waitFor();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export trace" }).click();
  const download = await downloadPromise;
  assert.equal(download.suggestedFilename(), "babysitter-demo-1084-trace.json");
  const content = [];
  for await (const chunk of await download.createReadStream())
    content.push(chunk);
  assert.equal(JSON.parse(Buffer.concat(content)).mode, "demo");
  await page.keyboard.press("Escape");
  await page.locator("nav").getByRole("link", { name: /Tasks/ }).click();
  await page.getByRole("searchbox", { name: "Search tasks" }).fill("token");
  assert.equal(await page.locator("tbody tr").count(), 1);
  await page
    .getByRole("searchbox", { name: "Search tasks" })
    .fill("no-match-possible");
  await page.getByRole("heading", { name: "No matching tasks" }).waitFor();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await page.getByLabel("Filter task status").selectOption("attention");
  assert.equal(await page.locator("tbody tr").count(), 2);
  await audit("tasks");
  for (const name of [
    "Verification",
    "Checkpoints",
    "Agent integrations",
    "Workspace",
  ]) {
    await page.locator("nav").getByRole("link", { name, exact: true }).click();
    await page.getByRole("heading", { name, exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.body.scrollWidth), 1440);
    await audit(name);
  }
  await page.getByLabel("Interface density").selectOption("compact");
  await page.getByLabel("Automatic refresh").selectOption("off");
  assert.equal(
    await page.evaluate(() => localStorage.getItem("bs-density")),
    "compact",
  );
  await page
    .getByRole("button", { name: "Set up an agent", exact: true })
    .click();
  await page.getByRole("button", { name: "Codex", exact: true }).click();
  await page.getByText("babysitter codex install", { exact: false }).waitFor();
  await audit("setup");
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Documentation", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Getting started", exact: true })
    .click();
  await page.getByRole("heading", { name: "1. Install the runtime" }).waitFor();
  await audit("offline guide");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+k");
  await page
    .getByRole("textbox", { name: "Search pages and tasks" })
    .fill("Handle expired");
  await page.getByRole("button", { name: /Handle expired/ }).click();
  await page.getByRole("tab", { name: "Timeline", exact: true }).waitFor();
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(base + "/#overview");
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  assert.equal(
    await page.evaluate(() => document.body.scrollWidth),
    390,
    "No horizontal page overflow on mobile",
  );
  await audit("mobile overview");
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page
    .locator("nav")
    .getByRole("link", { name: "Agent integrations" })
    .click();
  await page.getByRole("heading", { name: "Agent integrations" }).waitFor();
  assert.equal(await page.evaluate(() => document.body.scrollWidth), 390);
  // Untrusted content must be text, never executable DOM.
  const fixture = await (
    await context.request.get(base + "/api/workspace")
  ).json();
  fixture.tasks[0].goal = '<img src=x onerror="window.consoleXss=true">';
  await page.route("**/api/workspace", (r) => r.fulfill({ json: fixture }));
  await page.goto(base + "/#tasks");
  await page.reload();
  await page
    .getByRole("button", {
      name: '<img src=x onerror="window.consoleXss=true">',
    })
    .waitFor();
  assert.equal(await page.evaluate(() => window.consoleXss), undefined);
  assert.equal(await page.locator('img[src="x"]').count(), 0);
  await page.unroute("**/api/workspace");
  // Verify authentication UI and that the token is never persisted.
  await page.route("**/api/workspace", (r) =>
    r.request().headers().authorization === "Bearer local-test-console-token"
      ? r.fulfill({ json: fixture })
      : r.fulfill({ status: 401, json: { detail: "Console token required" } }),
  );
  await page.goto(base);
  await page.reload();
  await page
    .getByLabel("Console access token")
    .fill("local-test-console-token");
  await page
    .getByRole("button", { name: "Unlock console", exact: true })
    .click();
  await page.getByRole("heading", { name: "Overview", exact: true }).waitFor();
  assert.equal(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }).includes(
        "local-test-console-token",
      ),
    ),
    false,
  );
  await page.unroute("**/api/workspace");
  // Missing state is an empty workspace, not a fictional successful task.
  const empty = {
    ...fixture,
    tasks: [],
    activity: [],
    stats: {
      total: 0,
      active: 0,
      verified: 0,
      failed: 0,
      caught: 0,
      checkpoints: 0,
    },
  };
  await page.route("**/api/workspace", (r) => r.fulfill({ json: empty }));
  await page.goto(base);
  await page.reload();
  await page
    .getByRole("heading", { name: "Your first task starts here" })
    .waitFor();
  await page.unroute("**/api/workspace");
  await page.route("**/api/workspace", (r) =>
    r.fulfill({ status: 409, json: { detail: "Evidence unavailable" } }),
  );
  await page.goto(base);
  await page.reload();
  await page.getByRole("heading", { name: "Let’s reconnect." }).waitFor();
  assert.deepEqual(errors, [], "No uncaught browser exceptions");
  console.log(
    JSON.stringify(
      { interaction_checks: "passed", accessibility: reports },
      null,
      2,
    ),
  );
  assert.equal(
    reports.reduce((n, r) => n + r.violations.length, 0),
    0,
    "Fix accessibility findings above",
  );
} finally {
  if (reports.some((r) => r.violations.length))
    console.log(
      JSON.stringify(
        reports.filter((r) => r.violations.length),
        null,
        2,
      ),
    );
  await browser.close();
}

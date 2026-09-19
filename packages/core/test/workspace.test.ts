import { describe, expect, it } from "vitest";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Workspace } from "../src/workspace/workspace.js";

describe("Workspace", () => {
  it("backfills missing fields when opening a config.json from an older test0 version", async () => {
    const dir = await mkdtemp(join(tmpdir(), "test0-workspace-"));
    try {
      const rootDir = join(dir, ".test0");
      await mkdir(rootDir, { recursive: true });
      // Simulate a config.json written before `orchestrator`/`router` existed.
      await writeFile(
        join(rootDir, "config.json"),
        JSON.stringify({
          projectName: "legacy",
          routingPolicy: "quality-first",
          permissionRules: [],
          enabledSkills: [],
          enabledProviders: ["gemini"],
          mcpServers: [],
        }),
        "utf-8"
      );

      const workspace = await Workspace.open(dir);
      expect(workspace).toBeDefined();
      const config = await workspace!.loadConfig();
      expect(config.orchestrator.maxConcurrency).toBeGreaterThan(0);
      expect(config.router.retriesPerCandidate).toBeGreaterThanOrEqual(0);
      expect(config.skillPaths).toEqual([]);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  it("layers test0.config.yaml on top of stored config", async () => {
    const dir = await mkdtemp(join(tmpdir(), "test0-workspace-yaml-"));
    try {
      await writeFile(
        join(dir, "test0.config.yaml"),
        "router:\n  policy: free-first\npermissions:\n  terminal.execute: allow\n",
        "utf-8"
      );
      const workspace = await Workspace.init(dir, "yaml-project");
      const config = await workspace.loadConfig();
      expect(config.routingPolicy).toBe("free-first");
      expect(config.permissionRules.find((r) => r.scope === "terminal.execute")?.decision).toBe("allow");
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});

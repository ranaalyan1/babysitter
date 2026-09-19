import { describe, expect, it } from "vitest";
import { PermissionManager, DEFAULT_PERMISSION_RULES } from "../src/security/permissions.js";

describe("PermissionManager", () => {
  it("resolves exact-scope rules from the defaults", () => {
    const pm = new PermissionManager(DEFAULT_PERMISSION_RULES);
    expect(pm.check("filesystem.read").decision).toBe("allow");
    expect(pm.check("filesystem.delete").decision).toBe("ask");
    expect(pm.check("browser.purchase").decision).toBe("block");
  });

  it("defaults unknown scopes to 'ask' rather than silently allowing them", () => {
    const pm = new PermissionManager([]);
    const result = pm.check("some.unregistered.scope");
    expect(result.decision).toBe("ask");
    expect(result.allowed).toBe(false);
  });

  it("prefers the most specific matching rule", () => {
    const pm = new PermissionManager([
      { scope: "filesystem.*", decision: "allow" },
      { scope: "filesystem.delete", decision: "ask" },
    ]);
    expect(pm.check("filesystem.delete").decision).toBe("ask");
    expect(pm.check("filesystem.write").decision).toBe("allow");
  });

  it("records every check to the audit log", () => {
    const pm = new PermissionManager(DEFAULT_PERMISSION_RULES);
    pm.check("filesystem.read", "test-agent");
    pm.check("browser.purchase", "test-agent");
    const log = pm.getAuditLog();
    expect(log).toHaveLength(2);
    expect(log[0].actor).toBe("test-agent");
  });

  it("turns a resolved approval into a durable rule", () => {
    const pm = new PermissionManager([]);
    expect(pm.check("terminal.execute").decision).toBe("ask");
    pm.resolveApproval("terminal.execute", true);
    expect(pm.check("terminal.execute").decision).toBe("allow");
  });
});

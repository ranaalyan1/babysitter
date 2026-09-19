import { describe, expect, it } from "vitest";
import { MemoryStore } from "../src/memory/store.js";
import { ContextManager } from "../src/memory/context.js";

describe("MemoryStore", () => {
  it("remembers and recalls by scope and text", async () => {
    const store = new MemoryStore();
    await store.remember("project", "proj-1", "language", "Python", ["stack"]);
    await store.remember("project", "proj-1", "bug", "off-by-one in parser", ["bug"]);
    await store.remember("project", "proj-2", "language", "TypeScript", ["stack"]);

    const results = await store.recall({ scope: "proj-1" });
    expect(results).toHaveLength(2);

    const textResults = await store.recall({ text: "python" });
    expect(textResults.some((r) => r.key === "language" && r.scope === "proj-1")).toBe(true);
  });

  it("overwrites a record with the same type/scope/key instead of duplicating", async () => {
    const store = new MemoryStore();
    await store.remember("project", "proj-1", "language", "Python");
    await store.remember("project", "proj-1", "language", "Python 3.12");
    const all = await store.all();
    expect(all).toHaveLength(1);
    expect(all[0].value).toBe("Python 3.12");
  });
});

describe("ContextManager", () => {
  it("assembles context under a character budget without dumping everything", async () => {
    const store = new MemoryStore();
    await store.remember("project", "scope-1", "note", "x".repeat(5000), ["note"]);
    const context = new ContextManager(store);

    const assembled = await context.assemble({
      task: "do the thing",
      projectScope: "scope-1",
      budgetChars: 1000,
    });

    expect(assembled.approxChars).toBeLessThanOrEqual(1000 + "do the thing".length);
    // The task itself always makes it in even under a tight budget.
    expect(assembled.messages.some((m) => m.content.includes("do the thing"))).toBe(true);
  });
});

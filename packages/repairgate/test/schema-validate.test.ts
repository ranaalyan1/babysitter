import { describe, expect, it } from "vitest";
import { issuesToNudge, validateAgainstSchema, type JsonSchemaLike } from "../src/repair/schema-validate.js";

const toolSchema: JsonSchemaLike = {
  type: "object",
  required: ["path", "limit"],
  properties: {
    path: { type: "string" },
    limit: { type: "number" },
    recursive: { type: "boolean" },
    tags: { type: "array", items: { type: "string" } },
  },
};

describe("validateAgainstSchema", () => {
  it("passes clean, correctly-typed input", () => {
    const result = validateAgainstSchema({ path: "a.txt", limit: 10, recursive: true, tags: ["x"] }, toolSchema);
    expect(result.ok).toBe(true);
    expect(result.coerced).toBe(false);
  });

  it("flags a missing required field", () => {
    const result = validateAgainstSchema({ path: "a.txt" }, toolSchema);
    expect(result.ok).toBe(false);
    expect(result.issues.some((i) => i.path === "args.limit")).toBe(true);
  });

  it("coerces a stringly-typed number instead of failing", () => {
    const result = validateAgainstSchema({ path: "a.txt", limit: "10" }, toolSchema);
    expect(result.ok).toBe(true);
    expect(result.coerced).toBe(true);
    expect((result.value as Record<string, unknown>).limit).toBe(10);
  });

  it("coerces a stringly-typed boolean", () => {
    const result = validateAgainstSchema({ path: "a.txt", limit: 1, recursive: "true" }, toolSchema);
    expect(result.ok).toBe(true);
    expect((result.value as Record<string, unknown>).recursive).toBe(true);
  });

  it("wraps a bare scalar into a one-element array where an array was expected", () => {
    const result = validateAgainstSchema({ path: "a.txt", limit: 1, tags: "urgent" }, toolSchema);
    expect(result.ok).toBe(true);
    expect(result.coerced).toBe(true);
    expect((result.value as Record<string, unknown>).tags).toEqual(["urgent"]);
  });

  it("coerces a numeric path value to a string rather than failing (unambiguous coercion)", () => {
    const result = validateAgainstSchema({ path: 123, limit: 1 }, toolSchema);
    expect(result.ok).toBe(true);
    expect(result.coerced).toBe(true);
    expect((result.value as Record<string, unknown>).path).toBe("123");
  });

  it("flags a value of the wrong fundamental type that cannot be coerced", () => {
    const result = validateAgainstSchema({ path: { nested: true }, limit: 1 }, toolSchema);
    expect(result.ok).toBe(false);
    expect(result.issues.some((i) => i.path === "args.path")).toBe(true);
  });

  it("rejects the top-level value if it is not an object at all", () => {
    const result = validateAgainstSchema("not an object", toolSchema);
    expect(result.ok).toBe(false);
    expect(result.issues[0].path).toBe("args");
  });

  it("validates enum constraints", () => {
    const enumSchema: JsonSchemaLike = { type: "object", properties: { mode: { type: "string", enum: ["fast", "slow"] } } };
    expect(validateAgainstSchema({ mode: "fast" }, enumSchema).ok).toBe(true);
    expect(validateAgainstSchema({ mode: "medium" }, enumSchema).ok).toBe(false);
  });

  it("issuesToNudge produces a model-facing, per-field correction message", () => {
    const result = validateAgainstSchema({ path: "a.txt" }, toolSchema);
    const nudge = issuesToNudge("read_file", result.issues);
    expect(nudge).toContain("read_file");
    expect(nudge).toContain("args.limit");
    expect(nudge).toContain("corrected tool call");
  });
});

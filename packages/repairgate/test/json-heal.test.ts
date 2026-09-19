import { describe, expect, it } from "vitest";
import { healJson } from "../src/repair/json-heal.js";

describe("healJson", () => {
  it("parses already-valid JSON with zero fixes", () => {
    const result = healJson('{"a":1,"b":"two"}');
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ a: 1, b: "two" });
    expect(result.fixesApplied).toHaveLength(0);
  });

  it("strips a markdown code fence", () => {
    const result = healJson('```json\n{"a": 1}\n```');
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ a: 1 });
    expect(result.fixesApplied).toContain("strip-fences-or-prose");
  });

  it("strips surrounding prose", () => {
    const result = healJson('Sure! Here is the JSON you asked for: {"a": 1} Let me know if you need anything else.');
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ a: 1 });
  });

  it("quotes unquoted keys", () => {
    const result = healJson("{limit: 10, name: \"x\"}");
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ limit: 10, name: "x" });
  });

  it("converts single-quoted strings to double-quoted", () => {
    const result = healJson("{'name': 'value'}");
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ name: "value" });
  });

  it("removes trailing commas", () => {
    const result = healJson('{"a": 1, "b": 2,}');
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ a: 1, b: 2 });
  });

  it("inserts missing commas between array items", () => {
    const result = healJson('["a" "b" "c"]');
    expect(result.ok).toBe(true);
    expect(result.value).toEqual(["a", "b", "c"]);
  });

  it("closes unclosed/truncated brackets", () => {
    const result = healJson('{"a": 1, "b": [1, 2');
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ a: 1, b: [1, 2] });
  });

  it("normalizes Python/JS literals", () => {
    const result = healJson('{"a": True, "b": None, "c": undefined}');
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ a: true, b: null, c: null });
  });

  it("handles a combination of multiple failure modes at once", () => {
    const messy = "```json\n{name: 'Jane', active: True, tags: [\"a\" \"b\"],}\n```";
    const result = healJson(messy);
    expect(result.ok).toBe(true);
    expect(result.value).toEqual({ name: "Jane", active: true, tags: ["a", "b"] });
    expect(result.fixesApplied.length).toBeGreaterThan(1);
  });

  it("reports failure (not a throw) on truly unrecoverable garbage", () => {
    const result = healJson("this is not json at all, just words");
    expect(result.ok).toBe(false);
  });
});

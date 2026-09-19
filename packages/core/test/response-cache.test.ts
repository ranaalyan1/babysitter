import { describe, expect, it } from "vitest";
import { ResponseCache } from "../src/cache/response-cache.js";
import type { ModelMessage, ModelResponse } from "../src/types/index.js";

function response(content: string): ModelResponse {
  return {
    modelId: "m1",
    provider: "p1",
    content,
    usage: { inputTokens: 10, outputTokens: 5, costUsd: 0.001 },
    latencyMs: 5,
    finishReason: "stop",
  };
}

function messages(text: string): ModelMessage[] {
  return [{ role: "user", content: text }];
}

describe("ResponseCache", () => {
  it("misses on an empty cache", () => {
    const cache = new ResponseCache();
    expect(cache.get("m1", messages("hello world")).hit).toBe(false);
  });

  it("hits exactly on an identical prompt", () => {
    const cache = new ResponseCache();
    cache.set("m1", messages("What is the capital of France?"), response("Paris"));
    const result = cache.get("m1", messages("What is the capital of France?"));
    expect(result.hit).toBe(true);
    expect(result.matchType).toBe("exact");
    expect(result.response?.content).toBe("Paris");
  });

  it("hits exactly regardless of case/whitespace normalization", () => {
    const cache = new ResponseCache();
    cache.set("m1", messages("  Hello   World  "), response("hi"));
    const result = cache.get("m1", messages("hello world"));
    expect(result.hit).toBe(true);
    expect(result.matchType).toBe("exact");
  });

  it("hits semantically on a near-duplicate prompt above the threshold", () => {
    const cache = new ResponseCache({ similarityThreshold: 0.6 });
    cache.set("m1", messages("Summarize the quarterly financial report for the board"), response("summary"));
    const result = cache.get("m1", messages("Summarize the quarterly financial report for the board members"));
    expect(result.hit).toBe(true);
    expect(result.matchType).toBe("semantic");
    expect(result.similarity ?? 0).toBeGreaterThanOrEqual(0.6);
  });

  it("misses semantically on an unrelated prompt", () => {
    const cache = new ResponseCache({ similarityThreshold: 0.85 });
    cache.set("m1", messages("Summarize the quarterly financial report"), response("summary"));
    const result = cache.get("m1", messages("Write a poem about the ocean"));
    expect(result.hit).toBe(false);
  });

  it("never cross-matches between different models", () => {
    const cache = new ResponseCache();
    cache.set("m1", messages("hello world"), response("hi from m1"));
    expect(cache.get("m2", messages("hello world")).hit).toBe(false);
  });

  it("expires entries after the configured TTL", () => {
    const cache = new ResponseCache({ ttlMs: 1000 });
    const t0 = Date.now();
    cache.set("m1", messages("hello world"), response("hi"), t0);
    expect(cache.get("m1", messages("hello world"), t0 + 500).hit).toBe(true);
    expect(cache.get("m1", messages("hello world"), t0 + 1500).hit).toBe(false);
  });

  it("evicts the least-recently-used entry once maxEntries is exceeded", () => {
    const cache = new ResponseCache({ maxEntries: 1 });
    cache.set("m1", messages("first prompt"), response("first"));
    cache.set("m1", messages("second prompt"), response("second"));
    // The first, now-evicted exact entry should miss; the newest should still hit.
    expect(cache.get("m1", messages("first prompt")).hit).toBe(false);
    expect(cache.get("m1", messages("second prompt")).hit).toBe(true);
  });

  it("does nothing when disabled", () => {
    const cache = new ResponseCache({ enabled: false });
    cache.set("m1", messages("hello world"), response("hi"));
    expect(cache.get("m1", messages("hello world")).hit).toBe(false);
  });

  it("reports hit-rate stats across exact/semantic hits and misses", () => {
    const cache = new ResponseCache({ similarityThreshold: 0.5 });
    cache.set("m1", messages("hello world"), response("hi"));
    cache.get("m1", messages("hello world")); // exact hit
    cache.get("m1", messages("something totally unrelated query here")); // miss
    const stats = cache.stats();
    expect(stats.exactHits).toBe(1);
    expect(stats.misses).toBe(1);
    expect(stats.hitRatePercent).toBeCloseTo(50, 5);
  });
});

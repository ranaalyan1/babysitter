import { createHash } from "node:crypto";
import type { ModelMessage, ModelResponse } from "../types/index.js";

/**
 * Response cache (test0 V5, new in this pass), modeled on
 * [GPTCache](https://github.com/zilliztech/GPTCache): a two-tier cache
 * sitting in front of every model call so that repeated or
 * near-duplicate prompts are served instantly, at zero cost, instead of
 * hitting the provider again.
 *
 *  - **Exact tier** — an O(1) hash lookup on the normalized prompt +
 *    model id, exactly like GPTCache's default `pre_embedding_func`
 *    keying. Always correct: identical prompts get identical answers.
 *  - **Semantic tier** — GPTCache embeds prompts into a vector space and
 *    does a cosine-similarity nearest-neighbor search against a
 *    configurable threshold; test0 stays dependency-free and fully
 *    offline by approximating that with a bag-of-words Jaccard
 *    similarity over normalized tokens instead of real embeddings. It
 *    is intentionally documented as an approximation (see "What's
 *    simulated vs real" in docs/ARCHITECTURE.md) — swap `similarity()`
 *    for a real embedding + vector-store backend (e.g. via an MCP
 *    embeddings tool) to get GPTCache's actual recall/precision, while
 *    keeping the same `ResponseCache` interface and eviction/TTL/stats
 *    behavior.
 *
 * Every entry also tracks size-bounded LRU-ish eviction and a TTL, and
 * `stats()` reports exact/semantic hit rate the same way GPTCache's own
 * dashboards do, so a cache that's actively hurting correctness (too
 * loose a threshold) is visible rather than silently wrong.
 */
export interface ResponseCacheOptions {
  enabled?: boolean;
  /** Time-to-live for a cache entry, in ms. Default 5 minutes. */
  ttlMs?: number;
  /** Max entries kept per model before evicting the least-recently-used. Default 500. */
  maxEntries?: number;
  /** Jaccard similarity (0-1) required for a semantic hit. Default 0.85, GPTCache's commonly cited default. */
  similarityThreshold?: number;
}

export interface CacheLookupResult {
  hit: boolean;
  response?: ModelResponse;
  matchType?: "exact" | "semantic";
  similarity?: number;
}

interface CacheEntry {
  response: ModelResponse;
  tokens: Set<string>;
  storedAt: number;
  lastAccessedAt: number;
}

function normalize(text: string): string {
  return text.trim().toLowerCase().replace(/\s+/g, " ");
}

function tokenize(text: string): Set<string> {
  return new Set(normalize(text).split(/[^a-z0-9]+/).filter((t) => t.length > 1));
}

function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let intersection = 0;
  for (const t of a) if (b.has(t)) intersection++;
  const union = a.size + b.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

function fingerprint(modelId: string, promptKey: string): string {
  return createHash("sha1").update(`${modelId}::${promptKey}`).digest("hex");
}

export class ResponseCache {
  private readonly enabled: boolean;
  private readonly ttlMs: number;
  private readonly maxEntries: number;
  private readonly similarityThreshold: number;

  /** Exact-match tier: hash(modelId + normalized prompt) -> entry. */
  private exact = new Map<string, CacheEntry>();
  /** Semantic tier, bucketed per model so unrelated models never cross-match. */
  private semantic = new Map<string, Map<string, CacheEntry>>();

  private exactHits = 0;
  private semanticHits = 0;
  private misses = 0;

  constructor(options: ResponseCacheOptions = {}) {
    this.enabled = options.enabled ?? true;
    this.ttlMs = options.ttlMs ?? 5 * 60_000;
    this.maxEntries = options.maxEntries ?? 500;
    this.similarityThreshold = options.similarityThreshold ?? 0.85;
  }

  private promptKeyOf(messages: ModelMessage[]): string {
    return messages.map((m) => `${m.role}:${normalize(m.content)}`).join("\n");
  }

  private isExpired(entry: CacheEntry, now: number): boolean {
    return now - entry.storedAt > this.ttlMs;
  }

  get(modelId: string, messages: ModelMessage[], now = Date.now()): CacheLookupResult {
    if (!this.enabled) return { hit: false };
    const promptKey = this.promptKeyOf(messages);

    // 1) Exact tier — fastest, always correct.
    const key = fingerprint(modelId, promptKey);
    const exactEntry = this.exact.get(key);
    if (exactEntry && !this.isExpired(exactEntry, now)) {
      exactEntry.lastAccessedAt = now;
      this.exactHits++;
      return { hit: true, response: exactEntry.response, matchType: "exact", similarity: 1 };
    }
    if (exactEntry) this.exact.delete(key); // expired

    // 2) Semantic tier — nearest-neighbor by Jaccard similarity over this model's bucket.
    const bucket = this.semantic.get(modelId);
    if (bucket) {
      const queryTokens = tokenize(promptKey);
      let best: { entryKey: string; entry: CacheEntry; score: number } | undefined;
      for (const [entryKey, entry] of bucket) {
        if (this.isExpired(entry, now)) continue;
        const score = jaccard(queryTokens, entry.tokens);
        if (score >= this.similarityThreshold && (!best || score > best.score)) {
          best = { entryKey, entry, score };
        }
      }
      if (best) {
        best.entry.lastAccessedAt = now;
        this.semanticHits++;
        return { hit: true, response: best.entry.response, matchType: "semantic", similarity: best.score };
      }
    }

    this.misses++;
    return { hit: false };
  }

  set(modelId: string, messages: ModelMessage[], response: ModelResponse, now = Date.now()): void {
    if (!this.enabled) return;
    const promptKey = this.promptKeyOf(messages);
    const tokens = tokenize(promptKey);
    const entry: CacheEntry = { response, tokens, storedAt: now, lastAccessedAt: now };

    this.exact.set(fingerprint(modelId, promptKey), entry);
    this.evictIfNeeded(this.exact);

    let bucket = this.semantic.get(modelId);
    if (!bucket) {
      bucket = new Map();
      this.semantic.set(modelId, bucket);
    }
    bucket.set(promptKey, entry);
    this.evictIfNeeded(bucket);
  }

  private evictIfNeeded(map: Map<string, CacheEntry>): void {
    while (map.size > this.maxEntries) {
      let oldestKey: string | undefined;
      let oldestAt = Infinity;
      for (const [k, v] of map) {
        if (v.lastAccessedAt < oldestAt) {
          oldestAt = v.lastAccessedAt;
          oldestKey = k;
        }
      }
      if (oldestKey === undefined) break;
      map.delete(oldestKey);
    }
  }

  clear(): void {
    this.exact.clear();
    this.semantic.clear();
    this.exactHits = 0;
    this.semanticHits = 0;
    this.misses = 0;
  }

  stats() {
    const total = this.exactHits + this.semanticHits + this.misses;
    return {
      exactHits: this.exactHits,
      semanticHits: this.semanticHits,
      totalHits: this.exactHits + this.semanticHits,
      misses: this.misses,
      hitRatePercent: total === 0 ? 0 : ((this.exactHits + this.semanticHits) / total) * 100,
      exactCacheSize: this.exact.size,
      semanticCacheSize: [...this.semantic.values()].reduce((sum, b) => sum + b.size, 0),
    };
  }
}

import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { MemoryQuery, MemoryRecord, MemoryType } from "../types/index.js";

/**
 * Memory (section 10) + Context retrieval (section 11).
 *
 * A lightweight, file-backed store that supports retrieval by type/scope/
 * tags/text rather than blindly replaying the entire history into every
 * model call. Swap the persistence layer (e.g. for a vector DB) without
 * touching callers, since they only depend on `remember`/`recall`.
 */
export class MemoryStore {
  private records: MemoryRecord[] = [];
  private loaded = false;

  constructor(private readonly filePath?: string) {}

  private async ensureLoaded(): Promise<void> {
    if (this.loaded || !this.filePath) return;
    try {
      const raw = await readFile(this.filePath, "utf-8");
      this.records = JSON.parse(raw);
    } catch {
      this.records = [];
    }
    this.loaded = true;
  }

  private async persist(): Promise<void> {
    if (!this.filePath) return;
    await mkdir(dirname(this.filePath), { recursive: true });
    await writeFile(this.filePath, JSON.stringify(this.records, null, 2), "utf-8");
  }

  async remember(type: MemoryType, scope: string, key: string, value: unknown, tags: string[] = []): Promise<MemoryRecord> {
    await this.ensureLoaded();
    const now = new Date().toISOString();
    const existing = this.records.find((r) => r.type === type && r.scope === scope && r.key === key);
    if (existing) {
      existing.value = value;
      existing.tags = tags;
      existing.updatedAt = now;
      await this.persist();
      return existing;
    }
    const record: MemoryRecord = {
      id: randomUUID(),
      type,
      scope,
      key,
      value,
      tags,
      createdAt: now,
      updatedAt: now,
    };
    this.records.push(record);
    await this.persist();
    return record;
  }

  async recall(query: MemoryQuery): Promise<MemoryRecord[]> {
    await this.ensureLoaded();
    let results = this.records;
    if (query.type) results = results.filter((r) => r.type === query.type);
    if (query.scope) results = results.filter((r) => r.scope === query.scope);
    if (query.tags?.length) results = results.filter((r) => query.tags!.every((t) => r.tags.includes(t)));
    if (query.text) {
      const needle = query.text.toLowerCase();
      results = results.filter(
        (r) => r.key.toLowerCase().includes(needle) || JSON.stringify(r.value).toLowerCase().includes(needle)
      );
    }
    results = [...results].sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1));
    return query.limit ? results.slice(0, query.limit) : results;
  }

  async forget(type: MemoryType, scope: string, key: string): Promise<boolean> {
    await this.ensureLoaded();
    const before = this.records.length;
    this.records = this.records.filter((r) => !(r.type === type && r.scope === scope && r.key === key));
    const removed = this.records.length !== before;
    if (removed) await this.persist();
    return removed;
  }

  async all(): Promise<MemoryRecord[]> {
    await this.ensureLoaded();
    return [...this.records];
  }
}

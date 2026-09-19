import { describe, expect, it } from "vitest";
import { QuotaOrchestrator } from "../src/quota/orchestrator.js";

describe("QuotaOrchestrator", () => {
  it("allows calls with no configured quota or model limit", () => {
    const quota = new QuotaOrchestrator();
    expect(quota.reserve("task-1", "free-model").allowed).toBe(true);
  });

  it("enforces a task-scoped max-requests-per-model cap independent of any per-model rpm limit", () => {
    const quota = new QuotaOrchestrator({ maxRequestsPerModel: 2 });
    quota.record("task-1", "free-model", 10, 0);
    quota.record("task-1", "free-model", 10, 0);
    const result = quota.reserve("task-1", "free-model");
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("task-level");
  });

  it("keeps quota independent across different tasks against the same model", () => {
    const quota = new QuotaOrchestrator({ maxRequestsPerModel: 1 });
    quota.record("task-A", "free-model", 10, 0);
    expect(quota.reserve("task-A", "free-model").allowed).toBe(false);
    expect(quota.reserve("task-B", "free-model").allowed).toBe(true);
  });

  it("survives an agent firing many calls in a row up to its allotted slice, then blocks further ones", () => {
    const quota = new QuotaOrchestrator({ maxRequestsPerModel: 25 });
    for (let i = 0; i < 25; i++) {
      expect(quota.reserve("task-1", "free-model").allowed).toBe(true);
      quota.record("task-1", "free-model", 100, 0);
    }
    expect(quota.reserve("task-1", "free-model").allowed).toBe(false);
  });

  it("enforces a task-scoped total token cap per model", () => {
    const quota = new QuotaOrchestrator({ maxTokensPerModel: 1000 });
    quota.record("task-1", "free-model", 900, 0);
    expect(quota.reserve("task-1", "free-model", 200).allowed).toBe(false);
    expect(quota.reserve("task-1", "free-model", 50).allowed).toBe(true);
  });

  it("enforces a task-scoped total USD budget across every model combined", () => {
    const quota = new QuotaOrchestrator({ maxTaskBudgetUsd: 1 });
    quota.record("task-1", "model-a", 10, 0.6);
    quota.record("task-1", "model-b", 10, 0.5);
    expect(quota.reserve("task-1", "model-a").allowed).toBe(false);
    expect(quota.reserve("task-1", "model-c").allowed).toBe(false);
  });

  it("also enforces the underlying per-model rpm/tpm window (LiteLLM-style), composed with task-level quota", () => {
    const quota = new QuotaOrchestrator();
    quota.setModelLimit("free-model", { rpm: 1 });
    expect(quota.reserve("task-1", "free-model", 0).allowed).toBe(true);
    quota.record("task-1", "free-model", 10, 0);
    // A second reservation on the same model within the same 60s window is blocked at the model level.
    const check = quota.reserve("task-1", "free-model", 0);
    expect(check.allowed).toBe(false);
    expect(check.reason).toContain("model-level");
  });

  it("nextAvailableModel finds the first candidate a task can still afford", () => {
    const quota = new QuotaOrchestrator({ maxRequestsPerModel: 1 });
    quota.record("task-1", "free-model", 10, 0);
    const next = quota.nextAvailableModel("task-1", ["free-model", "backup-model"]);
    expect(next).toBe("backup-model");
  });

  it("reports usage for a task", () => {
    const quota = new QuotaOrchestrator();
    quota.record("task-1", "free-model", 100, 0.01);
    quota.record("task-1", "free-model", 50, 0.005);
    const usage = quota.usageForTask("task-1");
    expect(usage.perModelRequests["free-model"]).toBe(2);
    expect(usage.perModelTokens["free-model"]).toBe(150);
    expect(usage.totalSpentUsd).toBeCloseTo(0.015, 5);
  });

  it("resetTask clears a task's ledger", () => {
    const quota = new QuotaOrchestrator({ maxRequestsPerModel: 1 });
    quota.record("task-1", "free-model", 10, 0);
    quota.resetTask("task-1");
    expect(quota.reserve("task-1", "free-model").allowed).toBe(true);
  });
});

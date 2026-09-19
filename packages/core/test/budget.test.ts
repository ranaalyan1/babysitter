import { describe, expect, it } from "vitest";
import { BudgetManager } from "../src/budget/limiter.js";

describe("BudgetManager", () => {
  it("allows requests with no configured limit", () => {
    const budget = new BudgetManager();
    expect(budget.canProceed("any-model").allowed).toBe(true);
  });

  it("enforces an rpm limit within a 60s window", () => {
    const budget = new BudgetManager();
    budget.setLimit("m1", { rpm: 2 });
    const now = Date.now();

    expect(budget.canProceed("m1", 0, now).allowed).toBe(true);
    budget.record("m1", 10, 0, now);
    expect(budget.canProceed("m1", 0, now).allowed).toBe(true);
    budget.record("m1", 10, 0, now);
    expect(budget.canProceed("m1", 0, now).allowed).toBe(false);
  });

  it("recovers after the 60s window rolls forward", () => {
    const budget = new BudgetManager();
    budget.setLimit("m1", { rpm: 1 });
    const t0 = Date.now();
    budget.record("m1", 10, 0, t0);
    expect(budget.canProceed("m1", 0, t0).allowed).toBe(false);
    expect(budget.canProceed("m1", 0, t0 + 61_000).allowed).toBe(true);
  });

  it("enforces a tpm limit based on estimated tokens", () => {
    const budget = new BudgetManager();
    budget.setLimit("m1", { tpm: 100 });
    const now = Date.now();
    expect(budget.canProceed("m1", 50, now).allowed).toBe(true);
    budget.record("m1", 80, 0, now);
    expect(budget.canProceed("m1", 50, now).allowed).toBe(false);
  });

  it("enforces a lifetime spend cap", () => {
    const budget = new BudgetManager();
    budget.setLimit("m1", { maxBudgetUsd: 1 });
    const now = Date.now();
    budget.record("m1", 100, 0.6, now);
    expect(budget.canProceed("m1", 0, now).allowed).toBe(true);
    budget.record("m1", 100, 0.6, now);
    expect(budget.canProceed("m1", 0, now).allowed).toBe(false);
  });

  it("falls back to a wildcard '*' limit for models without a specific override", () => {
    const budget = new BudgetManager();
    budget.setLimit("*", { rpm: 1 });
    const now = Date.now();
    expect(budget.canProceed("any-model", 0, now).allowed).toBe(true);
    budget.record("any-model", 10, 0, now);
    expect(budget.canProceed("any-model", 0, now).allowed).toBe(false);
  });
});

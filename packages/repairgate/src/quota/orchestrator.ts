import { BudgetManager, type RateLimitConfig } from "@test0/core";

/**
 * Task-level quota orchestration — job #4 from the spec ("burn free
 * tiers across a *whole task*, not per-request. Survives an agent
 * firing 25 calls in a row.").
 *
 * Reuses test0's `BudgetManager` (LiteLLM-style sliding-window
 * rpm/tpm + spend-cap enforcement) as the per-model primitive — no
 * reason to reinvent rate-limit bookkeeping — but adds the piece a
 * stateless gateway cannot express: a **task-scoped** budget that
 * spans every request in one `Session`, independent of and *tighter
 * than* the per-model limits. A gateway checks "is this one request
 * over the model's rpm/tpm limit"; `QuotaOrchestrator` additionally
 * asks "has *this task* already burned its allotted slice of the free
 * tier", so one runaway agent looping 25 tool calls against a free
 * model can't silently exhaust the whole account's daily quota on a
 * single task while every other task starves.
 *
 * `reserve()` is a pre-call check exactly like `BudgetManager.canProceed`,
 * composed with it: a call must pass both the model-level window check
 * *and* the task-level remaining-budget check to proceed. When the
 * task's model-level quota is exhausted, `nextAvailableModel()` lets
 * the escalation ladder route around it — dovetailing directly with
 * job #3's escalation logic (an exhausted free tier is, from the
 * ladder's point of view, indistinguishable from a model that keeps
 * producing bad output: both mean "move to the next rung").
 */
export interface TaskQuota {
  /** Max requests this task may spend against a given model, across every step. */
  maxRequestsPerModel?: number;
  /** Max total tokens (input+output) this task may spend against a given model. */
  maxTokensPerModel?: number;
  /** Max total USD this task may spend across every model combined. */
  maxTaskBudgetUsd?: number;
}

interface TaskUsage {
  perModelRequests: Map<string, number>;
  perModelTokens: Map<string, number>;
  totalSpentUsd: number;
}

export interface ReserveResult {
  allowed: boolean;
  reason?: string;
}

export class QuotaOrchestrator {
  private readonly budget: BudgetManager;
  private readonly tasks = new Map<string, TaskUsage>();

  constructor(
    private readonly quota: TaskQuota = {},
    budget?: BudgetManager
  ) {
    this.budget = budget ?? new BudgetManager();
  }

  /** Configure the underlying per-model rpm/tpm/spend window, LiteLLM-style. Applies across all tasks. */
  setModelLimit(modelId: string, config: RateLimitConfig): void {
    this.budget.setLimit(modelId, config);
  }

  private usageOf(taskId: string): TaskUsage {
    let usage = this.tasks.get(taskId);
    if (!usage) {
      usage = { perModelRequests: new Map(), perModelTokens: new Map(), totalSpentUsd: 0 };
      this.tasks.set(taskId, usage);
    }
    return usage;
  }

  /** Pre-call check: does this task have quota left for one more call against this model, and is the model itself under its rpm/tpm window? */
  reserve(taskId: string, modelId: string, estimatedTokens = 0): ReserveResult {
    const modelCheck = this.budget.canProceed(modelId, estimatedTokens);
    if (!modelCheck.allowed) return { allowed: false, reason: `model-level: ${modelCheck.reason}` };

    const usage = this.usageOf(taskId);

    if (this.quota.maxRequestsPerModel !== undefined) {
      const used = usage.perModelRequests.get(modelId) ?? 0;
      if (used >= this.quota.maxRequestsPerModel) {
        return { allowed: false, reason: `task-level: ${used}/${this.quota.maxRequestsPerModel} requests already spent against "${modelId}" for this task` };
      }
    }

    if (this.quota.maxTokensPerModel !== undefined) {
      const used = usage.perModelTokens.get(modelId) ?? 0;
      if (used + estimatedTokens > this.quota.maxTokensPerModel) {
        return { allowed: false, reason: `task-level: ${used}+${estimatedTokens} would exceed ${this.quota.maxTokensPerModel} tokens against "${modelId}" for this task` };
      }
    }

    if (this.quota.maxTaskBudgetUsd !== undefined && usage.totalSpentUsd >= this.quota.maxTaskBudgetUsd) {
      return { allowed: false, reason: `task-level: task has already spent $${usage.totalSpentUsd.toFixed(4)} of its $${this.quota.maxTaskBudgetUsd} budget` };
    }

    return { allowed: true };
  }

  /** Post-call accounting: record real usage against both the model-level window and the task-level ledger. */
  record(taskId: string, modelId: string, tokens: number, costUsd: number): void {
    this.budget.record(modelId, tokens, costUsd);

    const usage = this.usageOf(taskId);
    usage.perModelRequests.set(modelId, (usage.perModelRequests.get(modelId) ?? 0) + 1);
    usage.perModelTokens.set(modelId, (usage.perModelTokens.get(modelId) ?? 0) + tokens);
    usage.totalSpentUsd += costUsd;
  }

  /** Given a ranked list of candidate model ids (weakest -> strongest), return the first one this task can still afford. */
  nextAvailableModel(taskId: string, candidateModelIds: string[], estimatedTokens = 0): string | undefined {
    return candidateModelIds.find((id) => this.reserve(taskId, id, estimatedTokens).allowed);
  }

  usageForTask(taskId: string) {
    const usage = this.usageOf(taskId);
    return {
      perModelRequests: Object.fromEntries(usage.perModelRequests),
      perModelTokens: Object.fromEntries(usage.perModelTokens),
      totalSpentUsd: usage.totalSpentUsd,
    };
  }

  resetTask(taskId: string): void {
    this.tasks.delete(taskId);
  }
}

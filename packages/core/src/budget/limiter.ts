/**
 * Budgets and rate limits (test0 V5, new in this pass), modeled on
 * LiteLLM's per-deployment `rpm`/`tpm` limits and per-key/team spend
 * budgets: without an explicit cap, a single misbehaving agent loop or a
 * burst of parallel orchestrator steps can blow through a provider's
 * real rate limit or run up real cost before anyone notices.
 *
 * `BudgetManager` enforces two independent dimensions per model, exactly
 * like LiteLLM recommends:
 *   - **rpm** (requests per minute) — a sliding 60s window request count.
 *   - **tpm** (tokens per minute) — a sliding 60s window token count,
 *     which matters more than rpm alone for agentic workloads where a
 *     single call can carry many thousands of tokens of context.
 * ...plus a **maxBudgetUsd** spend cap (lifetime or reset-period), for
 * the same reason LiteLLM tracks spend per virtual key/team.
 *
 * This is intentionally a pre-call *check* (`canProceed`) + a post-call
 * *record* (`record`), so the router can consult it before selecting a
 * candidate and skip anything already at its limit — the same
 * "optional_pre_call_checks" shape LiteLLM uses.
 */
export interface RateLimitConfig {
  rpm?: number;
  tpm?: number;
  maxBudgetUsd?: number;
}

export interface BudgetCheckResult {
  allowed: boolean;
  reason?: string;
}

interface WindowState {
  requestTimestamps: number[];
  tokenTimestamps: Array<{ at: number; tokens: number }>;
  spentUsd: number;
}

export class BudgetManager {
  private limits = new Map<string, RateLimitConfig>();
  private state = new Map<string, WindowState>();

  /** Use modelId "*" to set a default limit applied to every model without a specific override. */
  setLimit(modelId: string, config: RateLimitConfig): void {
    this.limits.set(modelId, config);
  }

  getLimit(modelId: string): RateLimitConfig | undefined {
    return this.limits.get(modelId) ?? this.limits.get("*");
  }

  private ensureState(modelId: string): WindowState {
    let s = this.state.get(modelId);
    if (!s) {
      s = { requestTimestamps: [], tokenTimestamps: [], spentUsd: 0 };
      this.state.set(modelId, s);
    }
    return s;
  }

  /** Pre-call check: would this model accept one more request right now? */
  canProceed(modelId: string, estimatedTokens = 0, now = Date.now()): BudgetCheckResult {
    const limit = this.getLimit(modelId);
    if (!limit) return { allowed: true };
    const state = this.ensureState(modelId);
    const windowStart = now - 60_000;

    if (limit.maxBudgetUsd !== undefined && state.spentUsd >= limit.maxBudgetUsd) {
      return { allowed: false, reason: `Budget exhausted: $${state.spentUsd.toFixed(4)} >= $${limit.maxBudgetUsd} cap` };
    }

    if (limit.rpm !== undefined) {
      const recent = state.requestTimestamps.filter((t) => t > windowStart).length;
      if (recent >= limit.rpm) {
        return { allowed: false, reason: `Rate limit: ${recent}/${limit.rpm} requests in the last 60s` };
      }
    }

    if (limit.tpm !== undefined) {
      const recentTokens = state.tokenTimestamps.filter((t) => t.at > windowStart).reduce((sum, t) => sum + t.tokens, 0);
      if (recentTokens + estimatedTokens > limit.tpm) {
        return { allowed: false, reason: `Token limit: ${recentTokens}+${estimatedTokens} would exceed ${limit.tpm} tpm` };
      }
    }

    return { allowed: true };
  }

  /** Post-call record: account for a completed request's tokens/cost. */
  record(modelId: string, tokens: number, costUsd: number, now = Date.now()): void {
    const state = this.ensureState(modelId);
    state.requestTimestamps.push(now);
    state.tokenTimestamps.push({ at: now, tokens });
    state.spentUsd += costUsd;

    // Trim old entries so the maps don't grow unbounded over a long-lived process.
    const windowStart = now - 60_000;
    state.requestTimestamps = state.requestTimestamps.filter((t) => t > windowStart);
    state.tokenTimestamps = state.tokenTimestamps.filter((t) => t.at > windowStart);
  }

  usage(modelId: string, now = Date.now()) {
    const state = this.ensureState(modelId);
    const windowStart = now - 60_000;
    return {
      requestsLastMinute: state.requestTimestamps.filter((t) => t > windowStart).length,
      tokensLastMinute: state.tokenTimestamps.filter((t) => t.at > windowStart).reduce((s, t) => s + t.tokens, 0),
      totalSpentUsd: state.spentUsd,
      limit: this.getLimit(modelId),
    };
  }

  resetSpend(modelId?: string): void {
    if (modelId) {
      const s = this.state.get(modelId);
      if (s) s.spentUsd = 0;
    } else {
      for (const s of this.state.values()) s.spentUsd = 0;
    }
  }
}

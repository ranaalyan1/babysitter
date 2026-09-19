import type {
  ModelDescriptor,
  ModelRequest,
  ModelResponse,
  RoutingDecision,
  RoutingPolicy,
  RoutingRequirements,
} from "../types/index.js";
import { ModelProviderError } from "../types/index.js";
import { ModelGateway } from "../models/gateway.js";
import type { BenchmarkStore } from "../benchmark/store.js";
import { HealthTracker, type HealthTrackerOptions } from "./health.js";
import { BudgetManager } from "../budget/limiter.js";
import { Tracer, type Trace } from "../observability/tracer.js";
import { estimateTokens } from "../models/providers/base.js";

export interface RouterOptions {
  policy?: RoutingPolicy;
  benchmarkStore?: BenchmarkStore;
  health?: HealthTrackerOptions;
  /** Per-candidate retry attempts before moving to the next candidate. Default 1 (no retry). */
  retriesPerCandidate?: number;
  /** Base delay for exponential backoff between retries, in ms. Default 200ms. */
  retryBackoffMs?: number;
  /** LiteLLM-style rpm/tpm/spend enforcement, shared across router instances if provided. */
  budget?: BudgetManager;
  /** Langfuse/OTel-style tracer; when provided, every route() call emits a trace + model spans. */
  tracer?: Tracer;
}

/**
 * The Intelligent Model Router (test0 V5 §4).
 *
 * Design borrows two proven ideas from production LLM gateways:
 *
 *  - LiteLLM's `Router`: a declarative model list, policy-driven ranking,
 *    and automatic fallback across a `fallback_models` chain when a
 *    deployment errors, rate-limits, or times out.
 *  - OpenRouter's provider routing: deprioritize (not permanently ban) a
 *    provider after a recent outage, weight remaining candidates by cost
 *    (inverse-square of price) rather than a hard cheapest-first cliff,
 *    and let the caller pin a policy (`:nitro` for latency, `:floor` for
 *    price) instead of guessing.
 *
 * Given task requirements, it:
 *  1. filters models by capability (coding/reasoning/vision/tool-use/context)
 *  2. drops any model whose circuit breaker is currently open (recent
 *     repeated failures — see `HealthTracker`)
 *  3. ranks the remaining candidates according to the active routing policy
 *  4. tries candidates in order (with bounded per-candidate retries),
 *     applying automatic fallback to the next candidate on failure
 *  5. returns a single unified ModelResponse regardless of which provider
 *     ultimately served the request, plus a full trace of what was tried
 */
export class ModelRouter {
  private policy: RoutingPolicy;
  private readonly benchmarkStore?: BenchmarkStore;
  private readonly health: HealthTracker;
  private readonly retriesPerCandidate: number;
  private readonly retryBackoffMs: number;
  readonly budget: BudgetManager;
  private readonly tracer?: Tracer;

  constructor(private readonly gateway: ModelGateway, options: RouterOptions = {}) {
    this.policy = options.policy ?? "quality-first";
    this.benchmarkStore = options.benchmarkStore;
    this.health = new HealthTracker(options.health);
    this.retriesPerCandidate = options.retriesPerCandidate ?? 1;
    this.retryBackoffMs = options.retryBackoffMs ?? 200;
    this.budget = options.budget ?? new BudgetManager();
    this.tracer = options.tracer;
  }

  setPolicy(policy: RoutingPolicy): void {
    this.policy = policy;
  }

  getPolicy(): RoutingPolicy {
    return this.policy;
  }

  getHealth(): HealthTracker {
    return this.health;
  }

  async selectCandidates(requirements: RoutingRequirements): Promise<ModelDescriptor[]> {
    const all = await this.gateway.listAllModels();

    let candidates = all.filter((m) => {
      if (requirements.requireVision && !m.capabilities.vision) return false;
      if (requirements.requireToolUse && !m.capabilities.toolUse) return false;
      if (requirements.minContextTokens && m.capabilities.maxContextTokens < requirements.minContextTokens) return false;
      if (requirements.maxLatencyMs && m.typicalLatencyMs > requirements.maxLatencyMs) return false;
      if (requirements.maxCostUsd !== undefined) {
        const perCall = m.cost.inputPerMillion + m.cost.outputPerMillion;
        if (perCall > requirements.maxCostUsd) return false;
      }
      if (requirements.excludedModels?.includes(m.id)) return false;
      return true;
    });

    // Availability check per provider (cached per call).
    const availability = new Map<string, boolean>();
    const filtered: ModelDescriptor[] = [];
    for (const m of candidates) {
      if (this.health.isOpen(m.id)) continue; // circuit breaker: recently failing repeatedly
      if (!this.budget.canProceed(m.id).allowed) continue; // rpm/tpm/spend cap reached
      if (!availability.has(m.provider)) {
        availability.set(m.provider, await this.gateway.checkAvailability(m.provider));
      }
      if (availability.get(m.provider)) filtered.push(m);
    }
    candidates = filtered;

    // Preferred models bubble to the front.
    if (requirements.preferredModels?.length) {
      const preferredSet = new Set(requirements.preferredModels);
      candidates.sort((a, b) => Number(preferredSet.has(b.id)) - Number(preferredSet.has(a.id)));
    }

    return this.rankByPolicy(candidates, requirements);
  }

  private capabilityScore(m: ModelDescriptor, requirements: RoutingRequirements): number {
    const raw =
      requirements.taskType === "coding"
        ? m.capabilities.coding
        : requirements.taskType === "reasoning" || requirements.taskType === "planning"
          ? m.capabilities.reasoning
          : (m.capabilities.coding + m.capabilities.reasoning) / 2;

    const benchmarkBoost = this.benchmarkStore?.getScore(m.id, requirements.taskType) ?? 0;
    return raw * 0.7 + benchmarkBoost * 0.3;
  }

  private rankByPolicy(candidates: ModelDescriptor[], requirements: RoutingRequirements): ModelDescriptor[] {
    const score = (m: ModelDescriptor) => this.capabilityScore(m, requirements);
    const sorted = [...candidates];

    switch (this.policy) {
      case "free-first":
        sorted.sort((a, b) => rank(a, b, [byFreeFirst, byScoreDesc(score)]));
        break;
      case "local-first":
        sorted.sort((a, b) => rank(a, b, [byLocalFirst, byFreeFirst, byScoreDesc(score)]));
        break;
      case "cheapest":
        // OpenRouter-style: weight by inverse-square of price instead of a
        // hard cliff, so a slightly pricier but much better model isn't
        // permanently buried behind the single cheapest option.
        sorted.sort((a, b) => byWeightedCost(a, b, score));
        break;
      case "fastest":
        sorted.sort((a, b) => a.typicalLatencyMs - b.typicalLatencyMs || byScoreDesc(score)(a, b));
        break;
      case "quality-first":
      default:
        sorted.sort((a, b) => byScoreDesc(score)(a, b));
        break;
    }
    return sorted;
  }

  /**
   * Route a request end-to-end: pick candidates, try each in order
   * (retrying transient failures a bounded number of times before giving
   * up on that candidate), and fall back automatically until one
   * succeeds or all candidates are exhausted.
   */
  async route(
    request: ModelRequest,
    requirements: RoutingRequirements,
    traceContext?: { trace: Trace; parentSpanId?: string }
  ): Promise<{ response: ModelResponse; decision: RoutingDecision }> {
    const candidates = await this.selectCandidates(requirements);
    if (candidates.length === 0) {
      throw new Error(
        `No available model satisfies requirements for task "${requirements.taskType}" (vision=${!!requirements.requireVision}, toolUse=${!!requirements.requireToolUse})`
      );
    }

    const attempted: RoutingDecision["attempted"] = [];

    for (const candidate of candidates) {
      const outcome = await this.tryCandidateWithRetries(candidate, request, traceContext);
      if (outcome.ok) {
        attempted.push({ modelId: candidate.id, outcome: "success" });
        const decision: RoutingDecision = {
          chosen: candidate,
          candidates,
          attempted,
          policy: this.policy,
          reason: `Selected ${candidate.displayName} under policy "${this.policy}" for task "${requirements.taskType}"`,
        };
        return { response: outcome.response, decision };
      }
      attempted.push({ modelId: candidate.id, outcome: outcome.kind });
    }

    throw new Error(
      `All ${candidates.length} candidate model(s) failed for task "${requirements.taskType}": ` +
        attempted.map((a) => `${a.modelId}(${a.outcome})`).join(", ")
    );
  }

  private async tryCandidateWithRetries(
    candidate: ModelDescriptor,
    request: ModelRequest,
    traceContext?: { trace: Trace; parentSpanId?: string }
  ): Promise<{ ok: true; response: ModelResponse } | { ok: false; kind: "rate-limited" | "unavailable" | "error" }> {
    let lastKind: "rate-limited" | "unavailable" | "error" = "error";
    const estimatedTokens = estimateTokens(request.messages.map((m) => m.content).join("\n"));

    for (let attempt = 0; attempt <= this.retriesPerCandidate; attempt++) {
      const budgetCheck = this.budget.canProceed(candidate.id, estimatedTokens);
      if (!budgetCheck.allowed) {
        lastKind = "rate-limited";
        this.health.recordFailure(candidate.id, budgetCheck.reason ?? "budget/rate limit");
        break;
      }

      const handle = traceContext?.trace
        ? this.tracer?.startSpan(traceContext.trace, `model:${candidate.id}`, "model", {
            parentSpanId: traceContext.parentSpanId,
            input: request.messages[request.messages.length - 1]?.content,
          })
        : undefined;

      const start = Date.now();
      try {
        const response = await this.gateway.complete(candidate.id, request);
        this.health.recordSuccess(candidate.id, Date.now() - start);
        this.budget.record(candidate.id, response.usage.inputTokens + response.usage.outputTokens, response.usage.costUsd);
        handle?.end({
          output: response.content,
          usage: { inputTokens: response.usage.inputTokens, outputTokens: response.usage.outputTokens, costUsd: response.usage.costUsd },
          attributes: { modelId: candidate.id, provider: candidate.provider, attempt },
        });
        return { ok: true, response };
      } catch (err) {
        const isProviderError = err instanceof ModelProviderError;
        const kind = isProviderError
          ? err.kind === "rate-limited"
            ? "rate-limited"
            : err.kind === "unavailable"
              ? "unavailable"
              : "error"
          : "error";
        lastKind = kind;
        const message = err instanceof Error ? err.message : String(err);
        this.health.recordFailure(candidate.id, message);
        handle?.end({ error: message, attributes: { modelId: candidate.id, provider: candidate.provider, attempt } });

        // Rate limits and hard unavailability rarely resolve within a few
        // hundred ms, so don't burn retry budget on them — fail straight
        // to the next candidate. Only transient/unknown errors get retried.
        const shouldRetry = kind === "error" && attempt < this.retriesPerCandidate;
        if (!shouldRetry) break;
        await sleep(this.retryBackoffMs * 2 ** attempt);
      }
    }
    return { ok: false, kind: lastKind };
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function byFreeFirst(a: ModelDescriptor, b: ModelDescriptor): number {
  return Number(b.cost.isFree) - Number(a.cost.isFree);
}

function byLocalFirst(a: ModelDescriptor, b: ModelDescriptor): number {
  return Number(b.category === "local") - Number(a.category === "local");
}

function byWeightedCost(a: ModelDescriptor, b: ModelDescriptor, score: (m: ModelDescriptor) => number): number {
  // weight = capabilityScore / price^2 (price floor avoids div-by-zero for free models,
  // which simply win outright as OpenRouter's free-tier candidates do).
  const weight = (m: ModelDescriptor) => {
    const price = m.cost.inputPerMillion + m.cost.outputPerMillion;
    if (price <= 0) return Number.POSITIVE_INFINITY;
    return score(m) / (price * price);
  };
  return weight(b) - weight(a);
}

function byScoreDesc(score: (m: ModelDescriptor) => number) {
  return (a: ModelDescriptor, b: ModelDescriptor) => score(b) - score(a);
}

function rank(a: ModelDescriptor, b: ModelDescriptor, comparators: Array<(a: ModelDescriptor, b: ModelDescriptor) => number>): number {
  for (const cmp of comparators) {
    const result = cmp(a, b);
    if (result !== 0) return result;
  }
  return 0;
}

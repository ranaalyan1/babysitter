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

export interface RouterOptions {
  policy?: RoutingPolicy;
  benchmarkStore?: BenchmarkStore;
}

/**
 * The Intelligent Model Router (section 4).
 *
 * Given task requirements, it:
 *  1. filters models by capability (coding/reasoning/vision/tool-use/context)
 *  2. ranks the remaining candidates according to the active routing policy
 *  3. tries candidates in order, applying automatic fallback on failure
 *  4. returns a single unified ModelResponse regardless of which provider
 *     ultimately served the request
 */
export class ModelRouter {
  private policy: RoutingPolicy;
  private readonly benchmarkStore?: BenchmarkStore;

  constructor(private readonly gateway: ModelGateway, options: RouterOptions = {}) {
    this.policy = options.policy ?? "quality-first";
    this.benchmarkStore = options.benchmarkStore;
  }

  setPolicy(policy: RoutingPolicy): void {
    this.policy = policy;
  }

  getPolicy(): RoutingPolicy {
    return this.policy;
  }

  async selectCandidates(requirements: RoutingRequirements): Promise<ModelDescriptor[]> {
    const all = await this.gateway.listAllModels();

    let candidates = all.filter((m) => {
      if (requirements.requireVision && !m.capabilities.vision) return false;
      if (requirements.requireToolUse && !m.capabilities.toolUse) return false;
      if (requirements.minContextTokens && m.capabilities.maxContextTokens < requirements.minContextTokens) return false;
      if (requirements.maxLatencyMs && m.typicalLatencyMs > requirements.maxLatencyMs) return false;
      if (requirements.excludedModels?.includes(m.id)) return false;
      return true;
    });

    // Availability check per provider (cached per call).
    const availability = new Map<string, boolean>();
    const filtered: ModelDescriptor[] = [];
    for (const m of candidates) {
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

  private rankByPolicy(candidates: ModelDescriptor[], requirements: RoutingRequirements): ModelDescriptor[] {
    const score = (m: ModelDescriptor): number => {
      const capabilityScore =
        requirements.taskType === "coding"
          ? m.capabilities.coding
          : requirements.taskType === "reasoning" || requirements.taskType === "planning"
            ? m.capabilities.reasoning
            : (m.capabilities.coding + m.capabilities.reasoning) / 2;

      const benchmarkBoost = this.benchmarkStore?.getScore(m.id, requirements.taskType) ?? 0;
      return capabilityScore * 0.7 + benchmarkBoost * 0.3;
    };

    const sorted = [...candidates];
    switch (this.policy) {
      case "free-first":
        sorted.sort((a, b) => rank(a, b, [byFreeFirst, byScoreDesc(score)]));
        break;
      case "local-first":
        sorted.sort((a, b) => rank(a, b, [byLocalFirst, byFreeFirst, byScoreDesc(score)]));
        break;
      case "cheapest":
        sorted.sort((a, b) => byCostAsc(a, b) || byScoreDesc(score)(a, b));
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
   * Route a request end-to-end: pick candidates, try each in order, and
   * fall back automatically on rate-limit/unavailable/error until one
   * succeeds or all candidates are exhausted.
   */
  async route(
    request: ModelRequest,
    requirements: RoutingRequirements
  ): Promise<{ response: ModelResponse; decision: RoutingDecision }> {
    const candidates = await this.selectCandidates(requirements);
    if (candidates.length === 0) {
      throw new Error(
        `No available model satisfies requirements for task "${requirements.taskType}" (vision=${!!requirements.requireVision}, toolUse=${!!requirements.requireToolUse})`
      );
    }

    const attempted: RoutingDecision["attempted"] = [];

    for (const candidate of candidates) {
      try {
        const response = await this.gateway.complete(candidate.id, request);
        attempted.push({ modelId: candidate.id, outcome: "success" });
        const decision: RoutingDecision = {
          chosen: candidate,
          candidates,
          attempted,
          policy: this.policy,
          reason: `Selected ${candidate.displayName} under policy "${this.policy}" for task "${requirements.taskType}"`,
        };
        return { response, decision };
      } catch (err) {
        if (err instanceof ModelProviderError) {
          const outcome = err.kind === "rate-limited" ? "rate-limited" : err.kind === "unavailable" ? "unavailable" : "error";
          attempted.push({ modelId: candidate.id, outcome });
          continue; // automatic fallback to next candidate
        }
        attempted.push({ modelId: candidate.id, outcome: "error" });
        continue;
      }
    }

    throw new Error(
      `All ${candidates.length} candidate model(s) failed for task "${requirements.taskType}": ` +
        attempted.map((a) => `${a.modelId}(${a.outcome})`).join(", ")
    );
  }
}

function byFreeFirst(a: ModelDescriptor, b: ModelDescriptor): number {
  return Number(b.cost.isFree) - Number(a.cost.isFree);
}

function byLocalFirst(a: ModelDescriptor, b: ModelDescriptor): number {
  return Number(b.category === "local") - Number(a.category === "local");
}

function byCostAsc(a: ModelDescriptor, b: ModelDescriptor): number {
  return a.cost.inputPerMillion + a.cost.outputPerMillion - (b.cost.inputPerMillion + b.cost.outputPerMillion);
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

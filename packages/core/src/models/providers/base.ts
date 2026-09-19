import type {
  ModelDescriptor,
  ModelProvider,
  ModelRequest,
  ModelResponse,
} from "../../types/index.js";
import { ModelProviderError } from "../../types/index.js";

/**
 * Shared helpers for building simple, deterministic model providers.
 *
 * Real deployments would replace `simulateCompletion` with actual HTTP
 * calls to the provider's API (or a browser-automation adapter for
 * browser-based access). The simulation here keeps test0 fully runnable
 * offline/in-sandbox while preserving the real control flow: latency,
 * token accounting, rate-limit/availability failures, and fallbacks.
 */
export abstract class BaseModelProvider implements ModelProvider {
  abstract id: string;
  abstract displayName: string;
  abstract category: ModelProvider["category"];

  protected abstract descriptors: ModelDescriptor[];

  /** Simple failure injection knobs so the router's fallback logic is testable. */
  protected failureMode: "none" | "rate-limited" | "unavailable" = "none";

  async listModels(): Promise<ModelDescriptor[]> {
    return this.descriptors;
  }

  async checkAvailability(): Promise<boolean> {
    if (this.failureMode === "unavailable") return false;
    return true;
  }

  setFailureMode(mode: "none" | "rate-limited" | "unavailable"): void {
    this.failureMode = mode;
  }

  async complete(modelId: string, request: ModelRequest): Promise<ModelResponse> {
    const descriptor = this.descriptors.find((m) => m.id === modelId);
    if (!descriptor) {
      throw new ModelProviderError(`Unknown model ${modelId} for provider ${this.id}`, this.id, "unknown");
    }

    if (this.failureMode === "unavailable") {
      throw new ModelProviderError(`${this.displayName} is currently unavailable`, this.id, "unavailable");
    }
    if (this.failureMode === "rate-limited") {
      throw new ModelProviderError(`${this.displayName} rate limit exceeded`, this.id, "rate-limited");
    }

    const start = Date.now();
    const content = this.simulateCompletion(descriptor, request);
    const latencyMs = Date.now() - start + descriptor.typicalLatencyMs;

    const inputTokens = estimateTokens(request.messages.map((m) => m.content).join("\n"));
    const outputTokens = estimateTokens(content);
    const costUsd = descriptor.cost.isFree
      ? 0
      : (inputTokens / 1_000_000) * descriptor.cost.inputPerMillion +
        (outputTokens / 1_000_000) * descriptor.cost.outputPerMillion;

    return {
      modelId,
      provider: this.id,
      content,
      usage: { inputTokens, outputTokens, costUsd },
      latencyMs,
      finishReason: "stop",
    };
  }

  /**
   * Subclasses provide a lightweight, deterministic "completion" so the
   * whole pipeline (router -> orchestrator -> agents) can run end-to-end
   * without network access. Swap this for a real API/browser call in
   * production adapters.
   */
  protected abstract simulateCompletion(descriptor: ModelDescriptor, request: ModelRequest): string;
}

export function estimateTokens(text: string): number {
  // Rough heuristic: ~4 characters per token.
  return Math.max(1, Math.ceil(text.length / 4));
}

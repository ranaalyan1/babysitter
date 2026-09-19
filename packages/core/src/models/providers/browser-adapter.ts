import type { ModelDescriptor, ModelRequest, ModelResponse } from "../../types/index.js";
import { ModelProviderError } from "../../types/index.js";
import { BaseModelProvider } from "./base.js";

export interface BrowserSessionAdapter {
  /** Confirms an authenticated browser session is present and usable. */
  hasValidSession(): Promise<boolean>;
  /** Sends a prompt through the browser UI and extracts the response text. */
  sendAndExtract(prompt: string): Promise<string>;
  /** Heuristically detects rate-limit banners/errors in the page. */
  detectRateLimit(): Promise<boolean>;
}

/**
 * Provider adapter for browser-based ("free browser access") model use,
 * as described in section 5 of the test0 spec.
 *
 * This class intentionally does NOT implement real browser automation —
 * that would depend on provider terms of service and a computer-use tool.
 * Instead it defines the adapter contract (session handling, availability
 * detection, response extraction, rate-limit detection, failure -> fallback)
 * so a concrete implementation (e.g. using a computer-use/browser MCP tool)
 * can be dropped in later without touching the router or orchestrator.
 */
export class BrowserModelProvider extends BaseModelProvider {
  id: string;
  displayName: string;
  category = "free-browser" as const;

  protected descriptors: ModelDescriptor[];

  constructor(
    private readonly session: BrowserSessionAdapter,
    opts: { id: string; displayName: string; descriptor: Omit<ModelDescriptor, "provider" | "category"> }
  ) {
    super();
    this.id = opts.id;
    this.displayName = opts.displayName;
    this.descriptors = [
      {
        ...opts.descriptor,
        provider: this.id,
        category: "free-browser",
      },
    ];
  }

  override async checkAvailability(): Promise<boolean> {
    try {
      return await this.session.hasValidSession();
    } catch {
      return false;
    }
  }

  override async complete(modelId: string, request: ModelRequest): Promise<ModelResponse> {
    const descriptor = this.descriptors.find((m) => m.id === modelId);
    if (!descriptor) {
      throw new ModelProviderError(`Unknown model ${modelId}`, this.id, "unknown");
    }

    const sessionOk = await this.session.hasValidSession();
    if (!sessionOk) {
      throw new ModelProviderError(`${this.displayName} browser session not authenticated`, this.id, "auth");
    }

    const rateLimited = await this.session.detectRateLimit();
    if (rateLimited) {
      throw new ModelProviderError(`${this.displayName} browser access is rate-limited`, this.id, "rate-limited");
    }

    const start = Date.now();
    const prompt = request.messages.map((m) => `${m.role}: ${m.content}`).join("\n");
    const content = await this.session.sendAndExtract(prompt);
    const latencyMs = Date.now() - start;

    return {
      modelId,
      provider: this.id,
      content,
      usage: { inputTokens: 0, outputTokens: 0, costUsd: 0 },
      latencyMs,
      finishReason: "stop",
    };
  }

  protected simulateCompletion(): string {
    throw new Error("BrowserModelProvider overrides complete() directly");
  }
}

/** A no-op session used for local dev/testing without real browser control. */
export class StubBrowserSession implements BrowserSessionAdapter {
  constructor(private readonly available = true) {}
  async hasValidSession(): Promise<boolean> {
    return this.available;
  }
  async sendAndExtract(prompt: string): Promise<string> {
    return `[browser-model stub] would send prompt of length ${prompt.length} and extract the reply`;
  }
  async detectRateLimit(): Promise<boolean> {
    return false;
  }
}

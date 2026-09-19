import type { ModelDescriptor } from "../../types/index.js";
import { BaseModelProvider } from "./base.js";

/** Example free-tier-API provider adapter: Google Gemini. */
export class GeminiProvider extends BaseModelProvider {
  id = "gemini";
  displayName = "Gemini";
  category = "free-api" as const;

  protected descriptors: ModelDescriptor[] = [
    {
      id: "gemini-2.0-flash",
      provider: this.id,
      displayName: "Gemini 2.0 Flash",
      category: "free-api",
      capabilities: {
        coding: 0.75,
        reasoning: 0.7,
        vision: true,
        toolUse: true,
        maxContextTokens: 1_000_000,
        streaming: true,
      },
      cost: { inputPerMillion: 0, outputPerMillion: 0, isFree: true },
      typicalLatencyMs: 600,
      available: true,
    },
    {
      id: "gemini-2.5-pro",
      provider: this.id,
      displayName: "Gemini 2.5 Pro",
      category: "free-api",
      capabilities: {
        coding: 0.9,
        reasoning: 0.92,
        vision: true,
        toolUse: true,
        maxContextTokens: 2_000_000,
        streaming: true,
      },
      cost: { inputPerMillion: 0, outputPerMillion: 0, isFree: true },
      typicalLatencyMs: 1400,
      available: true,
    },
  ];

  protected simulateCompletion(descriptor: ModelDescriptor, request: import("../../types/index.js").ModelRequest): string {
    const last = request.messages[request.messages.length - 1]?.content ?? "";
    return `[${descriptor.displayName}] response to: ${truncate(last)}`;
  }
}

function truncate(text: string, max = 120): string {
  return text.length > max ? text.slice(0, max) + "…" : text;
}

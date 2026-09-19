import type { ModelDescriptor, ModelRequest } from "../../types/index.js";
import { BaseModelProvider } from "./base.js";

/** Example paid/free-tier API provider adapter: DeepSeek. */
export class DeepSeekProvider extends BaseModelProvider {
  id = "deepseek";
  displayName = "DeepSeek";
  category = "paid-api" as const;

  protected descriptors: ModelDescriptor[] = [
    {
      id: "deepseek-v3",
      provider: this.id,
      displayName: "DeepSeek V3",
      category: "paid-api",
      capabilities: {
        coding: 0.88,
        reasoning: 0.85,
        vision: false,
        toolUse: true,
        maxContextTokens: 128_000,
        streaming: true,
      },
      cost: { inputPerMillion: 0.27, outputPerMillion: 1.1, isFree: false },
      typicalLatencyMs: 900,
      available: true,
    },
    {
      id: "deepseek-r1",
      provider: this.id,
      displayName: "DeepSeek R1 (reasoning)",
      category: "paid-api",
      capabilities: {
        coding: 0.85,
        reasoning: 0.95,
        vision: false,
        toolUse: false,
        maxContextTokens: 64_000,
        streaming: false,
      },
      cost: { inputPerMillion: 0.55, outputPerMillion: 2.19, isFree: false },
      typicalLatencyMs: 2500,
      available: true,
    },
  ];

  protected simulateCompletion(descriptor: ModelDescriptor, request: ModelRequest): string {
    const last = request.messages[request.messages.length - 1]?.content ?? "";
    return `[${descriptor.displayName}] response to: ${truncate(last)}`;
  }
}

function truncate(text: string, max = 120): string {
  return text.length > max ? text.slice(0, max) + "…" : text;
}

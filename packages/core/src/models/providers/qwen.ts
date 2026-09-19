import type { ModelDescriptor, ModelRequest } from "../../types/index.js";
import { BaseModelProvider } from "./base.js";

/** Example free-API provider adapter: Qwen. */
export class QwenProvider extends BaseModelProvider {
  id = "qwen";
  displayName = "Qwen";
  category = "free-api" as const;

  protected descriptors: ModelDescriptor[] = [
    {
      id: "qwen2.5-coder-32b",
      provider: this.id,
      displayName: "Qwen 2.5 Coder 32B",
      category: "free-api",
      capabilities: {
        coding: 0.86,
        reasoning: 0.72,
        vision: false,
        toolUse: true,
        maxContextTokens: 128_000,
        streaming: true,
      },
      cost: { inputPerMillion: 0, outputPerMillion: 0, isFree: true },
      typicalLatencyMs: 750,
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

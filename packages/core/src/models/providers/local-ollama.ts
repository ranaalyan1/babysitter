import type { ModelDescriptor, ModelRequest } from "../../types/index.js";
import { BaseModelProvider } from "./base.js";

/** Example local-model provider adapter: an Ollama-style local runtime. */
export class LocalOllamaProvider extends BaseModelProvider {
  id = "local-ollama";
  displayName = "Local Ollama";
  category = "local" as const;

  protected descriptors: ModelDescriptor[] = [
    {
      id: "llama3.1-8b",
      provider: this.id,
      displayName: "Llama 3.1 8B (local)",
      category: "local",
      capabilities: {
        coding: 0.6,
        reasoning: 0.55,
        vision: false,
        toolUse: false,
        maxContextTokens: 32_000,
        streaming: true,
      },
      cost: { inputPerMillion: 0, outputPerMillion: 0, isFree: true },
      typicalLatencyMs: 300,
      available: true,
    },
  ];

  async checkAvailability(): Promise<boolean> {
    // In a real adapter this would ping the local Ollama daemon
    // (e.g. GET http://localhost:11434/api/tags). We simulate "not
    // running" by default unless explicitly marked available, which
    // demonstrates the router's fallback behavior for local-first policy.
    return super.checkAvailability();
  }

  protected simulateCompletion(descriptor: ModelDescriptor, request: ModelRequest): string {
    const last = request.messages[request.messages.length - 1]?.content ?? "";
    return `[${descriptor.displayName}] response to: ${truncate(last)}`;
  }
}

function truncate(text: string, max = 120): string {
  return text.length > max ? text.slice(0, max) + "…" : text;
}

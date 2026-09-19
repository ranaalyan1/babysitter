import type { ModelBackend, ModelTurnRequest, ModelTurnResponse } from "../types.js";
import { rawCallsFromOpenAIToolCalls } from "../dialect/normalize.js";

/**
 * Real-provider extension point.
 *
 * repairgate ships with `DumbModel`/`ReliableModel` (see dumb-model.ts)
 * as deterministic, offline stand-ins so the repair engine and
 * escalation ladder are fully testable without network access or API
 * keys — the same "simulate first, adapt later" approach test0's core
 * package takes for its own model providers. `HttpModelBackend` is the
 * documented seam for going to production: point it at any
 * OpenAI-compatible free-tier endpoint (OpenRouter's free model pool,
 * Groq's free tier, a local Ollama server, any self-hosted vLLM/LM
 * Studio server) and it becomes a real rung on the escalation ladder.
 *
 * It intentionally implements only the OpenAI Chat Completions wire
 * shape, because that's the lowest common denominator every one of the
 * targets above accepts — `dialect/normalize.ts` already knows how to
 * translate a Cursor/Claude Code/Codex request into `ModelTurnRequest`
 * before it ever reaches here, so this adapter only has to go the
 * other direction once.
 */
export interface HttpModelBackendOptions {
  id: string;
  tier: number;
  baseUrl: string;
  apiKey?: string;
  model: string;
  /** Fetch-like implementation, injectable for testing. Defaults to global fetch. */
  fetchImpl?: typeof fetch;
}

interface OpenAICompatCompletion {
  choices: Array<{
    message: {
      content: string | null;
      tool_calls?: Array<{ id?: string; function: { name: string; arguments: string } }>;
    };
    finish_reason: string;
  }>;
  usage?: { prompt_tokens: number; completion_tokens: number };
}

export class HttpModelBackend implements ModelBackend {
  readonly id: string;
  readonly tier: number;

  constructor(private readonly options: HttpModelBackendOptions) {
    this.id = options.id;
    this.tier = options.tier;
  }

  async complete(request: ModelTurnRequest): Promise<ModelTurnResponse> {
    const doFetch = this.options.fetchImpl ?? fetch;
    const res = await doFetch(`${this.options.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(this.options.apiKey ? { Authorization: `Bearer ${this.options.apiKey}` } : {}),
      },
      body: JSON.stringify({
        model: this.options.model,
        messages: request.messages.map((m) => ({ role: m.role, content: m.content, name: m.name, tool_call_id: m.toolCallId })),
        tools: request.tools.map((t) => ({ type: "function", function: { name: t.name, description: t.description, parameters: t.parameters } })),
      }),
    });

    if (!res.ok) {
      throw new Error(`HttpModelBackend(${this.id}): provider returned HTTP ${res.status}`);
    }

    const data = (await res.json()) as OpenAICompatCompletion;
    const choice = data.choices[0];
    const toolCalls = rawCallsFromOpenAIToolCalls(choice?.message.tool_calls);

    return {
      content: choice?.message.content ?? "",
      toolCalls,
      finishReason: toolCalls.length > 0 ? "tool_calls" : choice?.finish_reason === "length" ? "length" : "stop",
      usage: data.usage ? { inputTokens: data.usage.prompt_tokens, outputTokens: data.usage.completion_tokens } : undefined,
    };
  }
}

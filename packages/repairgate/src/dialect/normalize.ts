import type { ModelTurnRequest, ModelTurnResponse, RawToolCall, ToolSpec } from "../types.js";

/**
 * Dialect normalization — job #5 from the spec ("Anthropic / OpenAI /
 * Responses in, any provider out."). This is deliberately the
 * thinnest piece of the product ("just enough dialect translation to
 * plug into one tool" — the spec calls steps 3–4 "plumbing you could
 * even borrow"): it converts each coding tool's wire format into
 * repairgate's internal `ModelTurnRequest`/`ModelTurnResponse` shape
 * (see ../types.ts) so the repair engine, escalation controller, and
 * quota orchestrator never need to know which dialect they're serving.
 *
 * Three dialects are covered because they cover the three coding tools
 * named in the brief:
 *  - **OpenAI Chat Completions** — `messages[]` + `tools[].function`,
 *    the format Cursor/most OpenAI-compatible clients speak.
 *  - **Anthropic Messages** — `system` is a top-level field (not a
 *    message), tool results come back as `tool_result` content blocks
 *    inside a `user` message, the format Claude Code speaks.
 *  - **OpenAI Responses API** — `input[]` items instead of `messages`,
 *    `function_call`/`function_call_output` item types instead of
 *    role-tagged messages, the format Codex/newer OpenAI SDKs speak.
 */
export type Dialect = "openai-chat" | "anthropic-messages" | "openai-responses";

// ---------------------------------------------------------------------------
// OpenAI Chat Completions
// ---------------------------------------------------------------------------

interface OpenAIChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  name?: string;
  tool_call_id?: string;
  tool_calls?: Array<{ id: string; type: "function"; function: { name: string; arguments: string } }>;
}

interface OpenAIChatTool {
  type: "function";
  function: { name: string; description?: string; parameters: ToolSpec["parameters"] };
}

export interface OpenAIChatRequest {
  messages: OpenAIChatMessage[];
  tools?: OpenAIChatTool[];
}

export function fromOpenAIChat(req: OpenAIChatRequest): ModelTurnRequest {
  const messages = req.messages.map((m) => ({
    role: m.role,
    content: m.content ?? "",
    name: m.name,
    toolCallId: m.tool_call_id,
  }));
  const tools: ToolSpec[] = (req.tools ?? []).map((t) => ({ name: t.function.name, description: t.function.description, parameters: t.function.parameters }));
  return { messages, tools, expectToolCall: tools.length > 0 };
}

export function toOpenAIChat(response: ModelTurnResponse): { role: "assistant"; content: string | null; tool_calls?: OpenAIChatMessage["tool_calls"] } {
  if (response.toolCalls.length === 0) {
    return { role: "assistant", content: response.content || null };
  }
  return {
    role: "assistant",
    content: null,
    tool_calls: response.toolCalls.map((c, i) => ({ id: c.id ?? `call_${i}`, type: "function", function: { name: c.name, arguments: c.argsText } })),
  };
}

// ---------------------------------------------------------------------------
// Anthropic Messages
// ---------------------------------------------------------------------------

type AnthropicContentBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: unknown }
  | { type: "tool_result"; tool_use_id: string; content: string };

interface AnthropicMessage {
  role: "user" | "assistant";
  content: string | AnthropicContentBlock[];
}

interface AnthropicTool {
  name: string;
  description?: string;
  input_schema: ToolSpec["parameters"];
}

export interface AnthropicMessagesRequest {
  system?: string;
  messages: AnthropicMessage[];
  tools?: AnthropicTool[];
}

export function fromAnthropicMessages(req: AnthropicMessagesRequest): ModelTurnRequest {
  const messages: ModelTurnRequest["messages"] = [];
  if (req.system) messages.push({ role: "system", content: req.system });

  for (const m of req.messages) {
    if (typeof m.content === "string") {
      messages.push({ role: m.role, content: m.content });
      continue;
    }
    for (const block of m.content) {
      if (block.type === "text") {
        messages.push({ role: m.role, content: block.text });
      } else if (block.type === "tool_result") {
        messages.push({ role: "tool", content: block.content, toolCallId: block.tool_use_id });
      } else if (block.type === "tool_use") {
        messages.push({ role: m.role, content: JSON.stringify({ tool_use: block.name, input: block.input }) });
      }
    }
  }

  const tools: ToolSpec[] = (req.tools ?? []).map((t) => ({ name: t.name, description: t.description, parameters: t.input_schema }));
  return { messages, tools, expectToolCall: tools.length > 0 };
}

export function toAnthropicMessages(response: ModelTurnResponse): { role: "assistant"; content: AnthropicContentBlock[] } {
  const blocks: AnthropicContentBlock[] = [];
  if (response.content) blocks.push({ type: "text", text: response.content });
  for (const [i, call] of response.toolCalls.entries()) {
    let input: unknown;
    try {
      input = JSON.parse(call.argsText);
    } catch {
      input = { _raw: call.argsText };
    }
    blocks.push({ type: "tool_use", id: call.id ?? `toolu_${i}`, name: call.name, input });
  }
  return { role: "assistant", content: blocks };
}

// ---------------------------------------------------------------------------
// OpenAI Responses API
// ---------------------------------------------------------------------------

type ResponsesItem =
  | { type: "message"; role: "system" | "user" | "assistant"; content: string }
  | { type: "function_call"; call_id: string; name: string; arguments: string }
  | { type: "function_call_output"; call_id: string; output: string };

interface ResponsesTool {
  type: "function";
  name: string;
  description?: string;
  parameters: ToolSpec["parameters"];
}

export interface OpenAIResponsesRequest {
  input: ResponsesItem[];
  tools?: ResponsesTool[];
}

export function fromOpenAIResponses(req: OpenAIResponsesRequest): ModelTurnRequest {
  const messages: ModelTurnRequest["messages"] = [];
  for (const item of req.input) {
    if (item.type === "message") {
      messages.push({ role: item.role, content: item.content });
    } else if (item.type === "function_call") {
      messages.push({ role: "assistant", content: JSON.stringify({ function_call: item.name, arguments: item.arguments }), toolCallId: item.call_id });
    } else if (item.type === "function_call_output") {
      messages.push({ role: "tool", content: item.output, toolCallId: item.call_id });
    }
  }
  const tools: ToolSpec[] = (req.tools ?? []).map((t) => ({ name: t.name, description: t.description, parameters: t.parameters }));
  return { messages, tools, expectToolCall: tools.length > 0 };
}

export function toOpenAIResponses(response: ModelTurnResponse): ResponsesItem[] {
  const items: ResponsesItem[] = [];
  if (response.content) items.push({ type: "message", role: "assistant", content: response.content });
  for (const [i, call] of response.toolCalls.entries()) {
    items.push({ type: "function_call", call_id: call.id ?? `call_${i}`, name: call.name, arguments: call.argsText });
  }
  return items;
}

// ---------------------------------------------------------------------------
// Raw tool-call extraction helper shared by provider adapters
// ---------------------------------------------------------------------------

/** Build a RawToolCall list from OpenAI-shaped tool_calls, tolerating a missing/undefined array. */
export function rawCallsFromOpenAIToolCalls(toolCalls: Array<{ id?: string; function: { name: string; arguments: string } }> | undefined): RawToolCall[] {
  return (toolCalls ?? []).map((c) => ({ id: c.id, name: c.function.name, argsText: c.function.arguments }));
}

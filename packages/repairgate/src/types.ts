import type { JsonSchemaLike } from "./repair/schema-validate.js";

/** A tool the calling coding-tool has declared, dialect-normalized (see dialect/normalize.ts). */
export interface ToolSpec {
  name: string;
  description?: string;
  parameters: JsonSchemaLike;
}

/** A tool call as emitted (possibly malformed) by the underlying model. */
export interface RawToolCall {
  id?: string;
  name: string;
  /** Raw argument text exactly as the model produced it — may not be valid JSON. */
  argsText: string;
}

/** A tool call after repair: valid JSON, schema-checked against its ToolSpec. */
export interface RepairedToolCall {
  id?: string;
  name: string;
  args: Record<string, unknown>;
}

export type RepairOutcome =
  | { kind: "clean"; call: RepairedToolCall }
  | { kind: "healed"; call: RepairedToolCall; fixesApplied: string[] }
  | { kind: "needs-retry"; nudge: string; reason: string }
  | { kind: "unrepairable"; reason: string };

export interface ModelTurnRequest {
  /** Full conversation so far, provider-agnostic (see dialect/normalize.ts). */
  messages: Array<{ role: "system" | "user" | "assistant" | "tool"; content: string; name?: string; toolCallId?: string }>;
  tools: ToolSpec[];
  /** Whether the calling tool expects at least one tool call in response (agentic step). */
  expectToolCall?: boolean;
}

export interface ModelTurnResponse {
  content: string;
  toolCalls: RawToolCall[];
  finishReason: "stop" | "tool_calls" | "length" | "error";
  usage?: { inputTokens: number; outputTokens: number };
}

/** A callable "dumb model" or real provider adapter. repairgate is provider-agnostic behind this. */
export interface ModelBackend {
  id: string;
  /** Relative capability rank used by the escalation ladder; higher = stronger/more expensive. */
  tier: number;
  complete(request: ModelTurnRequest): Promise<ModelTurnResponse>;
}

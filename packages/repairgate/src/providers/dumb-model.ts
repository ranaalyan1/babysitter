import type { ModelBackend, ModelTurnRequest, ModelTurnResponse, RawToolCall } from "../types.js";

/**
 * A deterministic, deliberately-bad simulated model, standing in for
 * "the worst free model you can find" so the repair engine and
 * escalation ladder are fully unit-testable offline — the same
 * approach test0's other providers (`gemini.ts`, `deepseek.ts`, ...)
 * take for the same reason: no network access or API keys required to
 * exercise real control flow. Swap `DumbModel`/`ReliableModel` for a
 * real HTTP-backed `ModelBackend` (see providers/http-backend.ts) to
 * point repairgate at an actual free-tier API.
 *
 * `DumbModel` cycles deterministically through the specific failure
 * modes weak models actually exhibit in practice (see json-heal.ts's
 * doc comment and the Mastra/json-repair-js precedent it cites):
 * markdown-fenced JSON, unquoted keys, trailing commas, a stringly
 * typed field, forgetting to call a tool at all, and calling a tool
 * that doesn't exist. A `failureRate` of 0 always emits perfectly
 * clean tool calls (useful as the "already works" baseline in tests);
 * higher rates emit a larger share of the failure modes, in a fixed
 * round-robin so tests are reproducible without needing a PRNG seed.
 */
export type DumbFailureMode = "clean" | "markdown-fenced" | "unquoted-keys" | "trailing-comma" | "stringly-typed" | "no-tool-call" | "unknown-tool" | "truncated";

export interface DumbModelOptions {
  id?: string;
  tier?: number;
  /** Fixed sequence of failure modes to cycle through, one per call. Defaults to a representative mix. */
  script?: DumbFailureMode[];
  /** Canned answer content to return alongside/instead of a tool call. */
  answerText?: string;
}

const DEFAULT_SCRIPT: DumbFailureMode[] = ["markdown-fenced", "unquoted-keys", "trailing-comma", "stringly-typed", "no-tool-call", "unknown-tool"];

export class DumbModel implements ModelBackend {
  readonly id: string;
  readonly tier: number;
  private callIndex = 0;

  constructor(private readonly options: DumbModelOptions = {}) {
    this.id = options.id ?? "dumb-free-model";
    this.tier = options.tier ?? 0;
  }

  private nextMode(): DumbFailureMode {
    const script = this.options.script ?? DEFAULT_SCRIPT;
    const mode = script[this.callIndex % script.length];
    this.callIndex++;
    return mode;
  }

  async complete(request: ModelTurnRequest): Promise<ModelTurnResponse> {
    const tool = request.tools[0];
    const mode = this.options.script ? this.nextMode() : "clean";

    if (!tool || mode === "no-tool-call") {
      return { content: this.options.answerText ?? "I think the answer is 42. Let me know if you need anything else!", toolCalls: [], finishReason: "stop" };
    }

    const args: Record<string, unknown> = buildSampleArgs(tool.parameters);
    const call = renderCallForMode(mode, tool.name, args);
    return { content: "", toolCalls: [call], finishReason: "tool_calls" };
  }
}

/** A "healthy" model stand-in: always emits clean, schema-valid tool calls. Used as the top rung of test ladders. */
export class ReliableModel implements ModelBackend {
  readonly id: string;
  readonly tier: number;

  constructor(options: DumbModelOptions = {}) {
    this.id = options.id ?? "reliable-strong-model";
    this.tier = options.tier ?? 10;
  }

  async complete(request: ModelTurnRequest): Promise<ModelTurnResponse> {
    const tool = request.tools[0];
    if (!tool) return { content: "Done.", toolCalls: [], finishReason: "stop" };
    const args = buildSampleArgs(tool.parameters);
    return { content: "", toolCalls: [{ id: "call_ok", name: tool.name, argsText: JSON.stringify(args) }], finishReason: "tool_calls" };
  }
}

function buildSampleArgs(schema: ModelTurnRequest["tools"][number]["parameters"]): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    const type = (prop as { type?: string }).type;
    args[key] = type === "number" || type === "integer" ? 1 : type === "boolean" ? true : type === "array" ? ["value"] : "value";
  }
  return args;
}

function renderCallForMode(mode: DumbFailureMode, toolName: string, args: Record<string, unknown>): RawToolCall {
  const clean = JSON.stringify(args);
  switch (mode) {
    case "clean":
      return { id: "call_1", name: toolName, argsText: clean };
    case "markdown-fenced":
      return { id: "call_1", name: toolName, argsText: "```json\n" + clean + "\n```" };
    case "unquoted-keys": {
      const unquoted = clean.replace(/"([a-zA-Z_][a-zA-Z0-9_]*)":/g, "$1:");
      return { id: "call_1", name: toolName, argsText: unquoted };
    }
    case "trailing-comma": {
      const withComma = clean.replace(/}$/, ",}").replace(/^\{/, "{");
      return { id: "call_1", name: toolName, argsText: withComma };
    }
    case "stringly-typed": {
      const stringified = Object.fromEntries(Object.entries(args).map(([k, v]) => [k, typeof v === "number" ? String(v) : v]));
      return { id: "call_1", name: toolName, argsText: JSON.stringify(stringified) };
    }
    case "unknown-tool":
      return { id: "call_1", name: `${toolName}_v2_final_REAL`, argsText: clean };
    case "truncated":
      return { id: "call_1", name: toolName, argsText: clean.slice(0, Math.max(1, clean.length - 3)) };
    case "no-tool-call":
    default:
      return { id: "call_1", name: toolName, argsText: clean };
  }
}

import { healJson } from "./json-heal.js";
import { issuesToNudge, validateAgainstSchema } from "./schema-validate.js";
import type { ModelBackend, ModelTurnRequest, RawToolCall, RepairOutcome, RepairedToolCall, ToolSpec } from "../types.js";

/**
 * The Repair Engine — job #2 from the spec ("validate every tool call
 * against its schema, fix broken JSON, retry-with-a-nudge when the
 * model forgets to call a tool"). This is the standalone, independently
 * testable core of the whole product: everything else in repairgate
 * (escalation, dialect shell, quota orchestration) exists to feed a
 * model turn into this engine and act on what comes out.
 *
 * Per attempt:
 *  1. Heal the raw argument text (`healJson` — markdown fences, prose,
 *     unquoted keys, trailing commas, ...).
 *  2. Validate + coerce the healed value against the tool's declared
 *     schema (`validateAgainstSchema` — Instructor-style: type
 *     coercion for the unambiguous cases, structured issues for the
 *     rest).
 *  3. If a tool call was required but the model just replied with
 *     prose (a very common weak-model failure — it "explains" instead
 *     of acting), that's also a repairable condition: a nudge asking
 *     it to actually call the tool, not describe it.
 *  4. On failure, build an Instructor-shaped nudge — the literal
 *     validation errors formatted for the model to read — append it to
 *     the conversation as a user turn, and let the caller (usually
 *     `EscalationController`) decide whether to retry the same model,
 *     retry with a nudge, or escalate.
 */
export interface RepairAttemptResult {
  outcomes: RepairOutcome[];
  /** True if every emitted tool call repaired cleanly (with or without JSON healing). */
  allRepaired: boolean;
  /** Nudge text to append as the next turn, if at least one call needs a retry. */
  nudge?: string;
}

export interface RepairEngineOptions {
  /** Max JSON-heal + schema-fix attempts is implicit (heal is single-pass); this bounds nudge retries per step. */
  maxNudgeRetries?: number;
}

export class RepairEngine {
  private readonly maxNudgeRetries: number;

  constructor(options: RepairEngineOptions = {}) {
    this.maxNudgeRetries = options.maxNudgeRetries ?? 2;
  }

  findTool(tools: ToolSpec[], name: string): ToolSpec | undefined {
    return tools.find((t) => t.name === name);
  }

  /** Repair a single raw tool call against its declared schema. Pure function — no model calls. */
  repairCall(raw: RawToolCall, tools: ToolSpec[]): RepairOutcome {
    const tool = this.findTool(tools, raw.name);
    if (!tool) {
      return { kind: "unrepairable", reason: `Model called unknown tool "${raw.name}" (not in the declared tool list)` };
    }

    const healed = healJson(raw.argsText);
    if (!healed.ok) {
      return {
        kind: "needs-retry",
        reason: `Could not parse arguments for "${raw.name}" as JSON, even after repair attempts`,
        nudge:
          `Your call to tool "${raw.name}" did not include valid JSON arguments ` +
          `(got: ${truncate(raw.argsText)}). Call "${raw.name}" again with a single valid JSON object as arguments.`,
      };
    }

    const validated = validateAgainstSchema(healed.value, tool.parameters);
    const call: RepairedToolCall = { id: raw.id, name: raw.name, args: validated.value as Record<string, unknown> };

    if (!validated.ok) {
      return { kind: "needs-retry", reason: `Schema validation failed for "${raw.name}"`, nudge: issuesToNudge(raw.name, validated.issues) };
    }

    if (healed.fixesApplied.length > 0 || validated.coerced) {
      return { kind: "healed", call, fixesApplied: healed.fixesApplied };
    }
    return { kind: "clean", call };
  }

  /**
   * Repair every tool call in a model turn, and detect the "forgot to
   * call a tool" failure mode (expectToolCall=true but the model
   * answered with prose instead).
   */
  repairTurn(rawCalls: RawToolCall[], tools: ToolSpec[], expectToolCall: boolean, _textContent: string): RepairAttemptResult {
    if (rawCalls.length === 0) {
      if (expectToolCall) {
        return {
          outcomes: [],
          allRepaired: false,
          nudge:
            "You did not call any tool, but this step requires one. " +
            `Available tools: ${tools.map((t) => t.name).join(", ")}. ` +
            "Respond with a single tool call, not an explanation.",
        };
      }
      return { outcomes: [], allRepaired: true };
    }

    const outcomes = rawCalls.map((c) => this.repairCall(c, tools));
    const nudges = outcomes.filter((o): o is Extract<RepairOutcome, { kind: "needs-retry" }> => o.kind === "needs-retry").map((o) => o.nudge);
    const unrepairableReasons = outcomes.filter((o): o is Extract<RepairOutcome, { kind: "unrepairable" }> => o.kind === "unrepairable").map((o) => o.reason);

    if (unrepairableReasons.length > 0) {
      return {
        outcomes,
        allRepaired: false,
        nudge: `${unrepairableReasons.join("\n")}\nAvailable tools: ${tools.map((t) => t.name).join(", ")}. Call one of these tools instead.`,
      };
    }
    if (nudges.length > 0) {
      return { outcomes, allRepaired: false, nudge: nudges.join("\n\n") };
    }
    return { outcomes, allRepaired: true };
  }

  /**
   * Drive up to `maxNudgeRetries` repair-and-nudge cycles against a
   * single backend for one step. Returns as soon as every tool call in
   * a turn repairs cleanly, or once retries are exhausted (the caller —
   * typically `EscalationController` — is expected to escalate at that
   * point, not retry forever against the same weak model).
   */
  async runStep(
    backend: ModelBackend,
    request: ModelTurnRequest
  ): Promise<{ success: true; calls: RepairedToolCall[]; attempts: number; healedAny: boolean } | { success: false; attempts: number; lastReason: string }> {
    let messages = [...request.messages];
    let healedAny = false;

    for (let attempt = 0; attempt <= this.maxNudgeRetries; attempt++) {
      const response = await backend.complete({ ...request, messages });
      const result = this.repairTurn(response.toolCalls, request.tools, request.expectToolCall ?? request.tools.length > 0, response.content);

      if (result.allRepaired) {
        const calls = result.outcomes
          .filter((o): o is Extract<RepairOutcome, { kind: "clean" | "healed" }> => o.kind === "clean" || o.kind === "healed")
          .map((o) => o.call);
        healedAny = healedAny || result.outcomes.some((o) => o.kind === "healed");
        return { success: true, calls, attempts: attempt + 1, healedAny };
      }

      if (attempt === this.maxNudgeRetries) {
        return { success: false, attempts: attempt + 1, lastReason: result.nudge ?? "unknown repair failure" };
      }

      messages = [...messages, { role: "assistant" as const, content: response.content }, { role: "user" as const, content: result.nudge ?? "Please retry." }];
    }

    return { success: false, attempts: this.maxNudgeRetries + 1, lastReason: "exhausted retries" };
  }
}

function truncate(text: string, max = 120): string {
  return text.length > max ? text.slice(0, max) + "…" : text;
}

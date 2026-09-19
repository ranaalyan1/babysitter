import { describe, expect, it } from "vitest";
import { RepairEngine } from "../src/repair/engine.js";
import { DumbModel, ReliableModel } from "../src/providers/dumb-model.js";
import type { ModelTurnRequest, ToolSpec } from "../src/types.js";

const readFileTool: ToolSpec = {
  name: "read_file",
  description: "Read a file",
  parameters: { type: "object", required: ["path"], properties: { path: { type: "string" }, limit: { type: "number" } } },
};

function request(overrides: Partial<ModelTurnRequest> = {}): ModelTurnRequest {
  return { messages: [{ role: "user", content: "Read the config file" }], tools: [readFileTool], expectToolCall: true, ...overrides };
}

describe("RepairEngine.repairCall", () => {
  const engine = new RepairEngine();

  it("passes through a clean call unchanged", () => {
    const outcome = engine.repairCall({ id: "1", name: "read_file", argsText: '{"path":"a.txt"}' }, [readFileTool]);
    expect(outcome.kind).toBe("clean");
  });

  it("heals a markdown-fenced call and reports the fix", () => {
    const outcome = engine.repairCall({ id: "1", name: "read_file", argsText: '```json\n{"path":"a.txt"}\n```' }, [readFileTool]);
    expect(outcome.kind).toBe("healed");
    if (outcome.kind === "healed") {
      expect(outcome.call.args.path).toBe("a.txt");
      expect(outcome.fixesApplied.length).toBeGreaterThan(0);
    }
  });

  it("flags an unknown tool as unrepairable", () => {
    const outcome = engine.repairCall({ id: "1", name: "delete_universe", argsText: "{}" }, [readFileTool]);
    expect(outcome.kind).toBe("unrepairable");
  });

  it("requests a retry with a schema-specific nudge for a missing required field", () => {
    const outcome = engine.repairCall({ id: "1", name: "read_file", argsText: "{}" }, [readFileTool]);
    expect(outcome.kind).toBe("needs-retry");
    if (outcome.kind === "needs-retry") {
      expect(outcome.nudge).toContain("path");
    }
  });
});

describe("RepairEngine.runStep against DumbModel", () => {
  it("succeeds immediately against a reliable model", async () => {
    const engine = new RepairEngine();
    const result = await engine.runStep(new ReliableModel(), request());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.attempts).toBe(1);
      expect(result.calls[0].name).toBe("read_file");
    }
  });

  it("heals a single-shot fixable malformed call without needing a nudge retry", async () => {
    const engine = new RepairEngine();
    const model = new DumbModel({ script: ["markdown-fenced"] });
    const result = await engine.runStep(model, request());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.healedAny).toBe(true);
    }
  });

  it("recovers via nudge retry when the model forgets to call a tool, then calls it", async () => {
    const engine = new RepairEngine({ maxNudgeRetries: 2 });
    // First turn: no tool call. Second turn onward (via the DumbModel's
    // internal state carrying over messages doesn't matter here since we
    // use a fresh model that always answers cleanly after the 1st turn)
    let turn = 0;
    const model = {
      id: "flaky",
      tier: 0,
      async complete(_req: ModelTurnRequest) {
        turn++;
        if (turn === 1) return { content: "The file contents are probably fine.", toolCalls: [], finishReason: "stop" as const };
        return { content: "", toolCalls: [{ id: "1", name: "read_file", argsText: '{"path":"a.txt"}' }], finishReason: "tool_calls" as const };
      },
    };
    const result = await engine.runStep(model, request());
    expect(result.success).toBe(true);
    if (result.success) expect(result.attempts).toBe(2);
  });

  it("fails after exhausting nudge retries against a persistently broken model", async () => {
    const engine = new RepairEngine({ maxNudgeRetries: 1 });
    const model = new DumbModel({ script: ["no-tool-call"] });
    const result = await engine.runStep(model, request());
    expect(result.success).toBe(false);
    if (!result.success) expect(result.attempts).toBe(2);
  });

  it("does not require a tool call when the request doesn't expect one", async () => {
    const engine = new RepairEngine();
    const model = new DumbModel({ script: ["no-tool-call"] });
    const result = await engine.runStep(model, request({ expectToolCall: false, tools: [] }));
    expect(result.success).toBe(true);
  });
});

describe("RepairEngine.repairTurn with a mix of calls in one turn", () => {
  const engine = new RepairEngine();

  it("flags the whole turn as unrepairable when one call among several targets an unknown tool", () => {
    const result = engine.repairTurn(
      [
        { id: "1", name: "read_file", argsText: '{"path":"a.txt"}' },
        { id: "2", name: "delete_universe", argsText: "{}" },
      ],
      [readFileTool],
      true,
      ""
    );

    expect(result.allRepaired).toBe(false);
    expect(result.outcomes[0].kind).toBe("clean");
    expect(result.outcomes[1].kind).toBe("unrepairable");
    expect(result.nudge).toContain("delete_universe");
    expect(result.nudge).toContain("read_file");
  });

  it("prioritizes surfacing the unrepairable reason over a needs-retry nudge when both occur in one turn", () => {
    const result = engine.repairTurn(
      [
        { id: "1", name: "read_file", argsText: "not json at all {{{" },
        { id: "2", name: "delete_universe", argsText: "{}" },
      ],
      [readFileTool],
      true,
      ""
    );

    expect(result.allRepaired).toBe(false);
    expect(result.nudge).toContain("delete_universe");
  });

  it("an unrepairable call in a turn causes runStep to fail even if the model never gets a chance to self-correct within budget", async () => {
    const engine2 = new RepairEngine({ maxNudgeRetries: 0 });
    const model = {
      id: "confused",
      tier: 0,
      async complete() {
        return {
          content: "",
          toolCalls: [
            { id: "1", name: "read_file", argsText: '{"path":"a.txt"}' },
            { id: "2", name: "not_a_real_tool", argsText: "{}" },
          ],
          finishReason: "tool_calls" as const,
        };
      },
    };
    const result = await engine2.runStep(model, request());
    expect(result.success).toBe(false);
    if (!result.success) expect(result.lastReason).toContain("not_a_real_tool");
  });
});

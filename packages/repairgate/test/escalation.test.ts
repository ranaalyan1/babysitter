import { describe, expect, it } from "vitest";
import { EscalationController } from "../src/escalation/controller.js";
import { Session } from "../src/session/session.js";
import { DumbModel, ReliableModel } from "../src/providers/dumb-model.js";
import { RepairEngine } from "../src/repair/engine.js";
import type { ModelTurnRequest, ToolSpec } from "../src/types.js";

const tool: ToolSpec = { name: "read_file", parameters: { type: "object", required: ["path"], properties: { path: { type: "string" } } } };

function request(): ModelTurnRequest {
  return { messages: [{ role: "user", content: "read it" }], tools: [tool], expectToolCall: true };
}

describe("EscalationController", () => {
  it("never escalates a step that the base model handles fine", async () => {
    const weak = new ReliableModel({ id: "weak", tier: 0 });
    const strong = new ReliableModel({ id: "strong", tier: 1 });
    const controller = new EscalationController({ models: [weak, strong] });
    const session = new Session("s1", "weak");

    const result = await controller.runStep(session, "step-1", request());
    expect(result.success).toBe(true);
    expect(result.modelId).toBe("weak");
    expect(result.escalated).toBe(false);
  });

  it("silently bumps to the next rung after the configured number of consecutive step failures", async () => {
    // "free model fails twice on a step" (failuresBeforeEscalation=2): the
    // calling tool retries the same step twice through the gateway before
    // the bump happens — each retry is a separate call to runStep with
    // the same stepId, exactly as a coding tool re-driving its own agent
    // loop would look from the outside.
    const weak = new DumbModel({ id: "weak", tier: 0, script: ["no-tool-call"] });
    const strong = new ReliableModel({ id: "strong", tier: 1 });
    const controller = new EscalationController({ models: [weak, strong], failuresBeforeEscalation: 2 }, new RepairEngine({ maxNudgeRetries: 0 }));
    const session = new Session("s1", "weak");

    const first = await controller.runStep(session, "step-1", request());
    expect(first.success).toBe(false);
    expect(first.escalated).toBe(false);

    const second = await controller.runStep(session, "step-1", request());
    expect(second.success).toBe(true);
    expect(second.modelId).toBe("strong");
    expect(second.escalated).toBe(true);

    const step = session.getStep("step-1");
    expect(step?.assignedModelId).toBe("strong");
    expect(session.getEscalations()).toHaveLength(1);
  });

  it("scopes escalation to a single step, not the whole session", async () => {
    const weak = new DumbModel({ id: "weak", tier: 0, script: ["no-tool-call"] });
    const strong = new ReliableModel({ id: "strong", tier: 1 });
    const controller = new EscalationController({ models: [weak, strong], failuresBeforeEscalation: 1 }, new RepairEngine({ maxNudgeRetries: 0 }));
    const session = new Session("s1", "weak");

    await controller.runStep(session, "step-hard", request());
    expect(session.getStep("step-hard")?.assignedModelId).toBe("strong");

    // A different, brand-new step in the SAME session should still start
    // on the weak base model — escalation must not leak session-wide.
    const otherStep = session.getOrCreateStep("step-easy");
    expect(otherStep.assignedModelId).toBe("weak");
  });

  it("returns failure without escalating before the failure threshold is reached", async () => {
    const weak = new DumbModel({ id: "weak", tier: 0, script: ["no-tool-call"] });
    const strong = new ReliableModel({ id: "strong", tier: 1 });
    const controller = new EscalationController({ models: [weak, strong], failuresBeforeEscalation: 3 }, new RepairEngine({ maxNudgeRetries: 0 }));
    const session = new Session("s1", "weak");

    const result = await controller.runStep(session, "step-1", request());
    expect(result.success).toBe(false);
    expect(result.escalated).toBe(false);
    expect(session.getStep("step-1")?.consecutiveFailures).toBe(1);
  });

  it("reports failure with a clear reason when already at the top of the ladder", async () => {
    const onlyModel = new DumbModel({ id: "solo", tier: 0, script: ["no-tool-call"] });
    const controller = new EscalationController({ models: [onlyModel], failuresBeforeEscalation: 1 }, new RepairEngine({ maxNudgeRetries: 0 }));
    const session = new Session("s1", "solo");

    const result = await controller.runStep(session, "step-1", request());
    expect(result.success).toBe(false);
    expect(result.reason).toContain("no further escalation possible");
  });

  it("resets the failure counter on the newly-escalated model after a success", async () => {
    const weak = new DumbModel({ id: "weak", tier: 0, script: ["no-tool-call"] });
    const strong = new ReliableModel({ id: "strong", tier: 1 });
    const controller = new EscalationController({ models: [weak, strong], failuresBeforeEscalation: 1 }, new RepairEngine({ maxNudgeRetries: 0 }));
    const session = new Session("s1", "weak");

    await controller.runStep(session, "step-1", request());
    expect(session.getStep("step-1")?.consecutiveFailures).toBe(0);
  });
});

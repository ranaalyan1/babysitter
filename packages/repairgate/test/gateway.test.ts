import { describe, expect, it } from "vitest";
import { RepairgateGateway } from "../src/gateway.js";
import { DumbModel, ReliableModel } from "../src/providers/dumb-model.js";
import type { ToolSpec } from "../src/types.js";

const tool: ToolSpec = { name: "read_file", parameters: { type: "object", required: ["path"], properties: { path: { type: "string" } } } };

describe("RepairgateGateway", () => {
  it("heals a malformed call end to end without the caller ever seeing raw broken JSON", async () => {
    const gateway = new RepairgateGateway({
      ladder: { models: [new DumbModel({ id: "weak", tier: 0, script: ["markdown-fenced"] }), new ReliableModel({ id: "strong", tier: 1 })] },
    });

    const result = await gateway.handleStep({
      sessionId: "session-1",
      messages: [{ role: "user", content: "read the config" }],
      tools: [tool],
      expectToolCall: true,
    });

    expect(result.success).toBe(true);
    expect(result.calls[0].name).toBe("read_file");
    expect(result.calls[0].args.path).toBe("value");
    expect(result.escalated).toBe(false);
  });

  it("silently escalates a persistently-failing step across repeated calls with the same sessionId/stepId", async () => {
    const gateway = new RepairgateGateway({
      ladder: {
        models: [new DumbModel({ id: "weak", tier: 0, script: ["no-tool-call"] }), new ReliableModel({ id: "strong", tier: 1 })],
        failuresBeforeEscalation: 2,
      },
    });

    const base = { sessionId: "session-1", stepId: "hard-step", messages: [{ role: "user" as const, content: "read it" }], tools: [tool], expectToolCall: true };

    const first = await gateway.handleStep(base);
    expect(first.success).toBe(false);

    const second = await gateway.handleStep(base);
    expect(second.success).toBe(true);
    expect(second.modelId).toBe("strong");
    expect(second.escalated).toBe(true);
  });

  it("tracks session state across multiple steps within one sessionId", async () => {
    const gateway = new RepairgateGateway({ ladder: { models: [new ReliableModel({ id: "weak", tier: 0 })] } });

    await gateway.handleStep({ sessionId: "session-1", messages: [{ role: "user", content: "step 1" }], tools: [tool] });
    await gateway.handleStep({ sessionId: "session-1", messages: [{ role: "user", content: "step 2" }], tools: [tool] });

    const session = gateway.sessions.get("session-1");
    expect(session).toBeDefined();
    expect(session?.allSteps().length).toBeGreaterThanOrEqual(2);
  });

  it("routes around a model that has exhausted its task-level quota", async () => {
    const gateway = new RepairgateGateway({
      ladder: { models: [new ReliableModel({ id: "weak", tier: 0 }), new ReliableModel({ id: "strong", tier: 1 })] },
      quota: { maxRequestsPerModel: 1 },
    });

    const first = await gateway.handleStep({ sessionId: "session-1", stepId: "s1", messages: [{ role: "user", content: "go" }], tools: [tool] });
    expect(first.modelId).toBe("weak");

    // Second step in the same session/task should be quota-blocked on
    // "weak" and transparently routed to "strong" instead.
    const second = await gateway.handleStep({ sessionId: "session-1", stepId: "s2", messages: [{ role: "user", content: "go again" }], tools: [tool] });
    expect(second.success).toBe(true);
    expect(second.modelId).toBe("strong");
  });

  it("reports quotaBlocked when every rung's quota is exhausted", async () => {
    const gateway = new RepairgateGateway({
      ladder: { models: [new ReliableModel({ id: "weak", tier: 0 })] },
      quota: { maxRequestsPerModel: 1 },
    });

    await gateway.handleStep({ sessionId: "session-1", stepId: "s1", messages: [{ role: "user", content: "go" }], tools: [tool] });
    const result = await gateway.handleStep({ sessionId: "session-1", stepId: "s2", messages: [{ role: "user", content: "go again" }], tools: [tool] });
    expect(result.success).toBe(false);
    expect(result.quotaBlocked).toBe(true);
  });
});

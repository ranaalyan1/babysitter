import { describe, expect, it } from "vitest";
import { ModelGateway } from "../src/models/gateway.js";
import { ModelRouter } from "../src/router/router.js";
import { GeminiProvider } from "../src/models/providers/gemini.js";
import { DeepSeekProvider } from "../src/models/providers/deepseek.js";
import { QwenProvider } from "../src/models/providers/qwen.js";

function buildGateway() {
  const gateway = new ModelGateway();
  const gemini = new GeminiProvider();
  const deepseek = new DeepSeekProvider();
  const qwen = new QwenProvider();
  gateway.registerProvider(gemini);
  gateway.registerProvider(deepseek);
  gateway.registerProvider(qwen);
  return { gateway, gemini, deepseek, qwen };
}

describe("ModelRouter", () => {
  it("selects the highest-capability model under quality-first policy", async () => {
    const { gateway } = buildGateway();
    const router = new ModelRouter(gateway, { policy: "quality-first" });
    const { decision } = await router.route(
      { messages: [{ role: "user", content: "hello" }] },
      { taskType: "coding" }
    );
    expect(decision.chosen.id).toBeDefined();
    expect(decision.policy).toBe("quality-first");
  });

  it("prefers free models under free-first policy", async () => {
    const { gateway } = buildGateway();
    const router = new ModelRouter(gateway, { policy: "free-first" });
    const candidates = await router.selectCandidates({ taskType: "coding" });
    expect(candidates[0].cost.isFree).toBe(true);
  });

  it("falls back to the next provider when one is rate-limited", async () => {
    const { gateway, gemini } = buildGateway();
    gemini.setFailureMode("rate-limited");
    const router = new ModelRouter(gateway, { policy: "quality-first" });

    const { decision } = await router.route(
      { messages: [{ role: "user", content: "hello" }] },
      { taskType: "coding" }
    );

    expect(decision.attempted[0]).toEqual({ modelId: "gemini-2.5-pro", outcome: "rate-limited" });
    expect(decision.chosen.provider).not.toBe("gemini");
  });

  it("falls back across multiple unavailable providers until one succeeds", async () => {
    const { gateway, gemini, deepseek } = buildGateway();
    gemini.setFailureMode("rate-limited");
    deepseek.setFailureMode("unavailable");
    const router = new ModelRouter(gateway, { policy: "quality-first" });

    const { response, decision } = await router.route(
      { messages: [{ role: "user", content: "hello" }] },
      { taskType: "coding" }
    );

    expect(response.provider).toBe("qwen");
    expect(decision.attempted.map((a) => a.outcome)).toContain("success");
  });

  it("throws a descriptive error when every candidate fails", async () => {
    const { gateway, gemini, deepseek, qwen } = buildGateway();
    gemini.setFailureMode("unavailable");
    deepseek.setFailureMode("unavailable");
    qwen.setFailureMode("unavailable");
    const router = new ModelRouter(gateway, { policy: "quality-first" });

    await expect(
      router.route({ messages: [{ role: "user", content: "hi" }] }, { taskType: "coding" })
    ).rejects.toThrow(/No available model/);
  });

  it("opens the circuit breaker after repeated failures and skips the model", async () => {
    const { gateway, gemini } = buildGateway();
    gemini.setFailureMode("rate-limited");
    const router = new ModelRouter(gateway, { policy: "quality-first", health: { allowedFails: 2, cooldownMs: 60_000 } });

    // Two failed attempts against gemini models trip the breaker (each
    // route() call only tries gemini once before falling back, so route
    // twice to accumulate consecutive failures on the same model id).
    await router.route({ messages: [{ role: "user", content: "1" }] }, { taskType: "coding" });
    await router.route({ messages: [{ role: "user", content: "2" }] }, { taskType: "coding" });

    const candidates = await router.selectCandidates({ taskType: "coding" });
    expect(candidates.some((c) => c.id === "gemini-2.5-pro")).toBe(false);
  });

  it("weights cheapest policy by capability/price^2 rather than a hard price cliff", async () => {
    const { gateway } = buildGateway();
    const router = new ModelRouter(gateway, { policy: "cheapest" });
    const candidates = await router.selectCandidates({ taskType: "coding" });
    // Free models (price=0) should always win under `cheapest`.
    expect(candidates[0].cost.isFree).toBe(true);
  });
});

import { describe, expect, it } from "vitest";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Tracer, toOtlpLikeJson } from "../src/observability/tracer.js";

describe("Tracer", () => {
  it("nests spans under a trace and marks it ok when all spans succeed", async () => {
    const tracer = new Tracer();
    const trace = tracer.startTrace("orchestration", { goal: "test" });
    const agentSpan = tracer.startSpan(trace, "agent:writer", "agent");
    const modelSpan = tracer.startSpan(trace, "model:gpt", "model", { parentSpanId: agentSpan.span.id });
    modelSpan.end({ output: "hi", usage: { inputTokens: 10, outputTokens: 5, costUsd: 0.01 }, attributes: { modelId: "gpt" } });
    agentSpan.end({ output: "done" });
    await tracer.endTrace(trace);

    expect(trace.status).toBe("ok");
    expect(trace.spans).toHaveLength(2);
    expect(trace.spans[1].parentSpanId).toBe(agentSpan.span.id);
    expect(trace.durationMs).toBeGreaterThanOrEqual(0);
  });

  it("marks the trace as error if any span errored", async () => {
    const tracer = new Tracer();
    const trace = tracer.startTrace("orchestration");
    const span = tracer.startSpan(trace, "model:gpt", "model");
    span.end({ error: "boom" });
    await tracer.endTrace(trace);
    expect(trace.status).toBe("error");
    expect(trace.spans[0].status).toBe("error");
  });

  it("persists traces to JSONL and reloads them", async () => {
    const dir = await mkdtemp(join(tmpdir(), "test0-tracer-"));
    const tracer = new Tracer(dir);
    const trace = tracer.startTrace("orchestration");
    tracer.startSpan(trace, "model:gpt", "model").end({ attributes: { modelId: "gpt" } });
    await tracer.endTrace(trace);

    const raw = await readFile(join(dir, "traces.jsonl"), "utf-8");
    expect(raw.trim().split("\n")).toHaveLength(1);

    const loaded = await tracer.loadPersistedTraces();
    expect(loaded).toHaveLength(1);
    expect(loaded[0].id).toBe(trace.id);
  });

  it("aggregates per-model usage across persisted traces", async () => {
    const dir = await mkdtemp(join(tmpdir(), "test0-tracer-"));
    const tracer = new Tracer(dir);

    for (const cost of [0.01, 0.02]) {
      const trace = tracer.startTrace("orchestration");
      const span = tracer.startSpan(trace, "model:gpt", "model");
      span.end({ usage: { costUsd: cost }, attributes: { modelId: "gpt" } });
      await tracer.endTrace(trace);
    }

    const summary = await tracer.usageSummary();
    expect(summary).toEqual([expect.objectContaining({ modelId: "gpt", calls: 2, totalCostUsd: expect.closeTo(0.03, 5) })]);
  });

  it("renders an OTel-shaped span list", () => {
    const tracer = new Tracer();
    const trace = tracer.startTrace("orchestration");
    tracer.startSpan(trace, "model:gpt", "model").end({});
    const otlp = toOtlpLikeJson(trace);
    expect(otlp.resourceSpans[0].scopeSpans[0].spans).toHaveLength(1);
    expect(otlp.resourceSpans[0].resource.attributes[0]).toEqual({ key: "service.name", value: { stringValue: "test0" } });
  });
});

import { randomUUID } from "node:crypto";
import { mkdir, appendFile, readFile } from "node:fs/promises";
import { join } from "node:path";

/**
 * Observability (test0 V5, new in this pass), modeled on how Langfuse and
 * OpenTelemetry structure LLM traces: a `Trace` is one end-to-end unit of
 * work (an orchestration run, a single `ask_model` call); it contains
 * nested `Span`s for every model call, tool call, or agent step inside
 * it, each carrying timing, token/cost usage, and status — the same
 * shape Langfuse uses for "trace -> observation" nesting, kept here as
 * plain JSON instead of requiring an OTel collector, so it works fully
 * offline while remaining easy to forward to a real OTel/Langfuse
 * backend later (see `toOtlpLikeJson`).
 */
export type SpanKind = "orchestration" | "agent" | "model" | "tool" | "plan";
export type SpanStatus = "ok" | "error";

export interface SpanUsage {
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
}

export interface Span {
  id: string;
  traceId: string;
  parentSpanId: string | null;
  name: string;
  kind: SpanKind;
  startedAt: string;
  endedAt?: string;
  durationMs?: number;
  status: SpanStatus;
  input?: unknown;
  output?: unknown;
  usage?: SpanUsage;
  error?: string;
  attributes?: Record<string, unknown>;
}

export interface Trace {
  id: string;
  name: string;
  startedAt: string;
  endedAt?: string;
  durationMs?: number;
  status: SpanStatus;
  spans: Span[];
  attributes?: Record<string, unknown>;
}

export interface ActiveSpanHandle {
  span: Span;
  end(result: { output?: unknown; usage?: SpanUsage; error?: string; attributes?: Record<string, unknown> }): void;
}

/**
 * In-memory tracer + optional JSONL persistence under `.test0/traces/`,
 * one line per completed trace — deliberately the simplest possible
 * format (à la LiteLLM's spend-logs table) rather than requiring a
 * running collector.
 */
export class Tracer {
  private traces = new Map<string, Trace>();

  constructor(private readonly persistPath?: string) {}

  startTrace(name: string, attributes?: Record<string, unknown>): Trace {
    const trace: Trace = {
      id: randomUUID(),
      name,
      startedAt: new Date().toISOString(),
      status: "ok",
      spans: [],
      attributes,
    };
    this.traces.set(trace.id, trace);
    return trace;
  }

  startSpan(trace: Trace, name: string, kind: SpanKind, opts: { parentSpanId?: string | null; input?: unknown } = {}): ActiveSpanHandle {
    const span: Span = {
      id: randomUUID(),
      traceId: trace.id,
      parentSpanId: opts.parentSpanId ?? null,
      name,
      kind,
      startedAt: new Date().toISOString(),
      status: "ok",
      input: opts.input,
    };
    const startMs = Date.now();
    trace.spans.push(span);

    return {
      span,
      end: (result) => {
        span.endedAt = new Date().toISOString();
        span.durationMs = Date.now() - startMs;
        span.output = result.output;
        span.usage = result.usage;
        span.attributes = { ...span.attributes, ...result.attributes };
        if (result.error) {
          span.status = "error";
          span.error = result.error;
        }
      },
    };
  }

  async endTrace(trace: Trace): Promise<void> {
    trace.endedAt = new Date().toISOString();
    trace.durationMs = Date.now() - new Date(trace.startedAt).getTime();
    trace.status = trace.spans.some((s) => s.status === "error") ? "error" : "ok";
    if (this.persistPath) {
      await mkdir(this.persistPath, { recursive: true });
      await appendFile(join(this.persistPath, "traces.jsonl"), JSON.stringify(trace) + "\n", "utf-8");
    }
  }

  getTrace(id: string): Trace | undefined {
    return this.traces.get(id);
  }

  listInMemoryTraces(): Trace[] {
    return [...this.traces.values()];
  }

  async loadPersistedTraces(limit = 50): Promise<Trace[]> {
    if (!this.persistPath) return [];
    try {
      const raw = await readFile(join(this.persistPath, "traces.jsonl"), "utf-8");
      const lines = raw.trim().split("\n").filter(Boolean);
      return lines
        .slice(-limit)
        .map((line) => JSON.parse(line) as Trace)
        .reverse();
    } catch {
      return [];
    }
  }

  /** Aggregate spend/usage across persisted traces, LiteLLM spend-logs style. */
  async usageSummary(): Promise<Array<{ modelId: string; calls: number; totalCostUsd: number; avgLatencyMs: number; errors: number }>> {
    const traces = await this.loadPersistedTraces(10_000);
    const byModel = new Map<string, { calls: number; totalCostUsd: number; totalLatency: number; errors: number }>();

    for (const trace of traces) {
      for (const span of trace.spans) {
        if (span.kind !== "model") continue;
        const modelId = String(span.attributes?.modelId ?? "unknown");
        const entry = byModel.get(modelId) ?? { calls: 0, totalCostUsd: 0, totalLatency: 0, errors: 0 };
        entry.calls += 1;
        entry.totalCostUsd += span.usage?.costUsd ?? 0;
        entry.totalLatency += span.durationMs ?? 0;
        if (span.status === "error") entry.errors += 1;
        byModel.set(modelId, entry);
      }
    }

    return [...byModel.entries()].map(([modelId, e]) => ({
      modelId,
      calls: e.calls,
      totalCostUsd: e.totalCostUsd,
      avgLatencyMs: e.calls ? e.totalLatency / e.calls : 0,
      errors: e.errors,
    }));
  }
}

/**
 * Renders a trace as an OpenTelemetry-shaped span list (resource +
 * spans with start/end nanos, status, attributes) so it can be forwarded
 * to a real OTel collector or a Langfuse OTel endpoint without test0
 * needing to depend on the OTel SDK itself.
 */
export function toOtlpLikeJson(trace: Trace) {
  return {
    resourceSpans: [
      {
        resource: { attributes: [{ key: "service.name", value: { stringValue: "test0" } }] },
        scopeSpans: [
          {
            scope: { name: "test0.tracer" },
            spans: trace.spans.map((s) => ({
              traceId: s.traceId,
              spanId: s.id,
              parentSpanId: s.parentSpanId ?? undefined,
              name: s.name,
              startTimeUnixNano: new Date(s.startedAt).getTime() * 1e6,
              endTimeUnixNano: s.endedAt ? new Date(s.endedAt).getTime() * 1e6 : undefined,
              status: { code: s.status === "ok" ? 1 : 2, message: s.error },
              attributes: Object.entries(s.attributes ?? {}).map(([key, value]) => ({ key, value: { stringValue: String(value) } })),
            })),
          },
        ],
      },
    ],
  };
}

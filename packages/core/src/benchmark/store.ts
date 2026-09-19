import type { BenchmarkCase, BenchmarkResult, BenchmarkSummary, TaskType } from "../types/index.js";
import { ModelGateway } from "../models/gateway.js";

/**
 * Reproducible benchmarking (section 15).
 *
 * Runs a fixed set of benchmark cases against models and stores results,
 * which the router can consult as one input (not the sole input) when
 * ranking candidates.
 */
export class BenchmarkStore {
  private results: BenchmarkResult[] = [];

  constructor(private readonly gateway: ModelGateway) {}

  async runSuite(modelId: string, cases: BenchmarkCase[]): Promise<BenchmarkResult[]> {
    const runResults: BenchmarkResult[] = [];
    for (const testCase of cases) {
      const start = Date.now();
      try {
        const response = await this.gateway.complete(modelId, {
          messages: [{ role: "user", content: testCase.prompt }],
          taskType: testCase.taskType,
        });
        // Providers report their own (simulated or real) latency; prefer
        // that over wall-clock time here since simulated adapters don't
        // actually block for their advertised latency.
        const latencyMs = response.latencyMs;
        const passed = testCase.expectedContains
          ? testCase.expectedContains.every((needle) => response.content.toLowerCase().includes(needle.toLowerCase()))
          : true;
        runResults.push({
          modelId,
          caseId: testCase.id,
          passed,
          latencyMs,
          costUsd: response.usage.costUsd,
        });
      } catch (err) {
        runResults.push({
          modelId,
          caseId: testCase.id,
          passed: false,
          latencyMs: Date.now() - start,
          costUsd: 0,
          notes: err instanceof Error ? err.message : String(err),
        });
      }
    }
    this.results.push(...runResults);
    return runResults;
  }

  getSummary(modelId: string): BenchmarkSummary {
    const forModel = this.results.filter((r) => r.modelId === modelId);
    const passed = forModel.filter((r) => r.passed).length;
    const avgLatencyMs = forModel.length ? forModel.reduce((s, r) => s + r.latencyMs, 0) / forModel.length : 0;
    const totalCostUsd = forModel.reduce((s, r) => s + r.costUsd, 0);
    return {
      modelId,
      totalCases: forModel.length,
      passed,
      avgLatencyMs,
      totalCostUsd,
      score: forModel.length ? passed / forModel.length : 0,
    };
  }

  /** Consulted by the router: a coarse 0-1 boost per model/taskType. */
  getScore(modelId: string, _taskType: TaskType): number {
    const summary = this.getSummary(modelId);
    return summary.totalCases ? summary.score : 0;
  }

  allResults(): BenchmarkResult[] {
    return [...this.results];
  }
}

export const DEFAULT_BENCHMARK_CASES: BenchmarkCase[] = [
  {
    id: "coding-basic",
    taskType: "coding",
    prompt: "Write a function that reverses a string.",
    expectedContains: ["reverse"],
  },
  {
    id: "reasoning-basic",
    taskType: "reasoning",
    prompt: "If a train travels 60 miles in 1.5 hours, what is its average speed?",
    expectedContains: ["train"],
  },
  {
    id: "instruction-following",
    taskType: "general",
    prompt: "Reply with exactly the single word: acknowledged",
    expectedContains: ["acknowledged"],
  },
];

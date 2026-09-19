import type { Command } from "commander";
import chalk from "chalk";
import Table from "cli-table3";
import { Test0Runtime } from "@test0/core";

/**
 * Surfaces the Langfuse/OpenTelemetry-inspired trace log recorded by
 * `Tracer` (see packages/core/src/observability/tracer.ts) plus the
 * LiteLLM-style per-model rpm/tpm/spend usage tracked by `BudgetManager`.
 */
export function registerTracesCommand(program: Command): void {
  const cmd = program.command("traces").description("Inspect recorded orchestration traces and per-model spend/usage");

  cmd
    .command("list", { isDefault: true })
    .description("List recent traces (most recent first)")
    .option("-n, --limit <n>", "max traces to show", "20")
    .action(async (opts: { limit: string }) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const traces = await runtime.tracer.loadPersistedTraces(Number(opts.limit) || 20);

      if (traces.length === 0) {
        console.log(chalk.yellow("No traces recorded yet. Run `test0 run \"<goal>\"` first."));
        return;
      }

      const table = new Table({
        head: [chalk.bold("Trace"), chalk.bold("Name"), chalk.bold("Status"), chalk.bold("Spans"), chalk.bold("Duration"), chalk.bold("Started")],
        style: { head: [], border: [] },
      });
      for (const t of traces) {
        table.push([
          t.id.slice(0, 8),
          t.name,
          t.status === "ok" ? chalk.green(t.status) : chalk.red(t.status),
          String(t.spans.length),
          `${t.durationMs ?? 0}ms`,
          new Date(t.startedAt).toLocaleString(),
        ]);
      }
      console.log(table.toString());
    });

  cmd
    .command("show <traceId>")
    .description("Show every span in a trace (prefix match on trace id)")
    .action(async (traceId: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const traces = await runtime.tracer.loadPersistedTraces(10_000);
      const trace = traces.find((t) => t.id === traceId || t.id.startsWith(traceId));
      if (!trace) {
        console.error(chalk.red(`No trace found matching "${traceId}"`));
        process.exitCode = 1;
        return;
      }

      console.log(chalk.bold(`${trace.name}  `) + chalk.dim(trace.id));
      console.log(`Status: ${trace.status === "ok" ? chalk.green(trace.status) : chalk.red(trace.status)}  Duration: ${trace.durationMs}ms\n`);

      const table = new Table({
        head: [chalk.bold("Span"), chalk.bold("Kind"), chalk.bold("Status"), chalk.bold("Duration"), chalk.bold("Usage")],
        style: { head: [], border: [] },
      });
      for (const s of trace.spans) {
        const usage = s.usage ? `${s.usage.inputTokens ?? 0}+${s.usage.outputTokens ?? 0} tok / $${(s.usage.costUsd ?? 0).toFixed(4)}` : "-";
        table.push([
          s.name,
          s.kind,
          s.status === "ok" ? chalk.green(s.status) : chalk.red(`${s.status}: ${s.error ?? ""}`),
          `${s.durationMs ?? 0}ms`,
          usage,
        ]);
      }
      console.log(table.toString());
    });

  cmd
    .command("usage")
    .description("Aggregate spend/latency/error counts per model, LiteLLM spend-logs style")
    .action(async () => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const summary = await runtime.tracer.usageSummary();

      if (summary.length === 0) {
        console.log(chalk.yellow("No model usage recorded yet."));
        return;
      }

      const table = new Table({
        head: [chalk.bold("Model"), chalk.bold("Calls"), chalk.bold("Total Cost"), chalk.bold("Avg Latency"), chalk.bold("Errors")],
        style: { head: [], border: [] },
      });
      for (const row of summary) {
        table.push([row.modelId, String(row.calls), `$${row.totalCostUsd.toFixed(4)}`, `${Math.round(row.avgLatencyMs)}ms`, String(row.errors)]);
      }
      console.log(table.toString());

      console.log("\n" + chalk.bold("LIVE RATE LIMIT / BUDGET STATE (this process)\n"));
      const liveTable = new Table({
        head: [chalk.bold("Model"), chalk.bold("Req/min"), chalk.bold("Tokens/min"), chalk.bold("Spent"), chalk.bold("Limit")],
        style: { head: [], border: [] },
      });
      for (const row of summary) {
        const u = runtime.budget.usage(row.modelId);
        const limit = u.limit ? `rpm=${u.limit.rpm ?? "-"} tpm=${u.limit.tpm ?? "-"} cap=$${u.limit.maxBudgetUsd ?? "-"}` : "none";
        liveTable.push([row.modelId, String(u.requestsLastMinute), String(u.tokensLastMinute), `$${u.totalSpentUsd.toFixed(4)}`, limit]);
      }
      console.log(liveTable.toString());
    });
}

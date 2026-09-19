import type { Command } from "commander";
import chalk from "chalk";
import Table from "cli-table3";
import { Test0Runtime, DEFAULT_BENCHMARK_CASES } from "@test0/core";

export function registerModelsCommand(program: Command): void {
  const cmd = program.command("models").description("List available models and routing policy");

  cmd.action(async () => {
    const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
    console.log(chalk.bold("AVAILABLE MODELS\n"));

    const table = new Table({
      head: [chalk.bold("Model"), chalk.bold("Provider"), chalk.bold("Category"), chalk.bold("Cost"), chalk.bold("Latency"), chalk.bold("Status")],
      style: { head: [], border: [] },
    });

    for (const provider of runtime.gateway.listProviders()) {
      const available = await provider.checkAvailability();
      const models = await provider.listModels();
      for (const m of models) {
        const cost = m.cost.isFree ? chalk.green("free") : `$${m.cost.inputPerMillion}/$${m.cost.outputPerMillion} per 1M`;
        const health = runtime.router.getHealth().snapshot(m.id);
        const circuitOpen = runtime.router.getHealth().isOpen(m.id);
        const status = !available
          ? chalk.red("provider down")
          : circuitOpen
            ? chalk.red(`circuit open (${health.consecutiveFailures} fails)`)
            : chalk.green("healthy");
        table.push([m.id, provider.displayName, m.category, cost, `~${m.typicalLatencyMs}ms`, status]);
      }
    }

    console.log(table.toString());
    console.log("");
    console.log(`Routing: ${chalk.cyan("AUTO")}`);
    console.log(`Policy:  ${chalk.cyan(runtime.router.getPolicy().toUpperCase())}`);
  });

  cmd
    .command("set-policy <policy>")
    .description("Set routing policy: free-first | quality-first | local-first | cheapest | fastest")
    .action(async (policy: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const config = await runtime.workspace.loadConfig();
      config.routingPolicy = policy as typeof config.routingPolicy;
      await runtime.workspace.saveConfig(config);
      console.log(chalk.green(`✓ Routing policy set to ${policy}`));
    });

  cmd
    .command("bench [modelId]")
    .description("Run the reproducible benchmark suite against one model or every available model")
    .action(async (modelId?: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const targets = modelId ? [modelId] : (await runtime.gateway.listAllModels()).map((m) => m.id);

      const table = new Table({
        head: [chalk.bold("Model"), chalk.bold("Passed"), chalk.bold("Avg Latency"), chalk.bold("Total Cost"), chalk.bold("Score")],
        style: { head: [], border: [] },
      });

      for (const id of targets) {
        await runtime.benchmarks.runSuite(id, DEFAULT_BENCHMARK_CASES);
        const summary = runtime.benchmarks.getSummary(id);
        table.push([
          id,
          `${summary.passed}/${summary.totalCases}`,
          `${Math.round(summary.avgLatencyMs)}ms`,
          `$${summary.totalCostUsd.toFixed(4)}`,
          summary.score.toFixed(2),
        ]);
      }

      console.log(table.toString());
    });
}

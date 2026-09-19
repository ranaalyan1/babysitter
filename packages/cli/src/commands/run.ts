import type { Command } from "commander";
import chalk from "chalk";
import ora from "ora";
import { Test0Runtime } from "@test0/core";

export function registerRunCommand(program: Command): void {
  program
    .command("run <goal>")
    .description("Run an orchestrated task: test0 plans, selects models/skills/tools, and executes")
    .option("-p, --policy <policy>", "routing policy override")
    .action(async (goal: string, opts: { policy?: string }) => {
      const runtime = await Test0Runtime.load({
        projectDir: process.cwd(),
        routingPolicy: opts.policy as never,
      });

      console.log(chalk.bold(`Goal: ${goal}\n`));
      const spinner = ora("Planning and executing...").start();

      let result;
      try {
        result = await runtime.orchestrator.run(goal);
      } catch (err) {
        spinner.fail("Orchestration failed to start");
        throw err;
      }
      spinner.stop();

      for (const step of result.plan.steps) {
        const stepResult = result.stepResults.find((r) => r.stepId === step.id);
        const icon = step.status === "done" ? chalk.green("✓") : chalk.red("✗");
        console.log(`${icon} [${step.assignedRole}] ${step.description}`);
        if (stepResult?.modelUsed) console.log(chalk.dim(`    model: ${stepResult.modelUsed}`));
        if (step.status === "failed" && stepResult) console.log(chalk.red(`    error: ${stepResult.summary}`));
      }

      console.log("");
      console.log(result.finalReport);

      await runtime.workspace.appendTaskHistory({ goal, success: result.success, steps: result.plan.steps.length });
      await runtime.shutdown();
      process.exitCode = result.success ? 0 : 1;
    });
}

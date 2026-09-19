import type { Command } from "commander";
import chalk from "chalk";
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
      console.log(chalk.dim("Planning..."));
      const result = await runtime.orchestrator.run(goal);

      console.log("");
      for (const step of result.plan.steps) {
        const stepResult = result.stepResults.find((r) => r.stepId === step.id);
        const icon = step.status === "done" ? chalk.green("✓") : chalk.red("✗");
        console.log(`${icon} [${step.assignedRole}] ${step.description}`);
        if (stepResult?.modelUsed) console.log(chalk.dim(`    model: ${stepResult.modelUsed}`));
      }

      console.log("");
      console.log(result.finalReport);

      await runtime.workspace.appendTaskHistory({ goal, success: result.success, steps: result.plan.steps.length });
    });
}

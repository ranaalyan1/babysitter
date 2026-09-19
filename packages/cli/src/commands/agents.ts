import type { Command } from "commander";
import chalk from "chalk";
import { DEFAULT_AGENTS } from "@test0/core";

export function registerAgentsCommand(program: Command): void {
  program
    .command("agents")
    .description("List specialized agents available to the orchestrator")
    .action(() => {
      console.log(chalk.bold("SPECIALIZED AGENTS\n"));
      for (const agent of DEFAULT_AGENTS) {
        console.log(`${chalk.cyan(agent.id)} ${chalk.dim(`(${agent.role})`)}`);
        console.log(`  ${agent.description}`);
        if (agent.goal) console.log(chalk.dim(`  goal:      ${agent.goal}`));
        if (agent.backstory) console.log(chalk.dim(`  backstory: ${agent.backstory}`));
        console.log(chalk.dim(`  skills:    ${agent.skills.join(", ") || "none"}`));
        console.log(chalk.dim(`  tools:     ${agent.tools.join(", ") || "none"}`));
        console.log("");
      }
    });
}

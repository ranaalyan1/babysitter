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
        console.log(`- ${chalk.cyan(agent.id)} (${agent.role}) — ${agent.description}`);
        console.log(`    skills: ${agent.skills.join(", ") || "none"}`);
        console.log(`    tools:  ${agent.tools.join(", ") || "none"}`);
      }
    });
}

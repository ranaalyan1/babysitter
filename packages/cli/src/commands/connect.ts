import type { Command } from "commander";
import chalk from "chalk";
import { Test0Runtime } from "@test0/core";

export function registerConnectCommand(program: Command): void {
  program
    .command("connect")
    .description("Check connectivity/availability for all registered model providers")
    .action(async () => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      console.log(chalk.bold("Checking provider connectivity...\n"));
      for (const provider of runtime.gateway.listProviders()) {
        const available = await provider.checkAvailability();
        const icon = available ? chalk.green("✓") : chalk.red("✗");
        console.log(`${icon} ${provider.displayName} (${provider.category})`);
      }
    });
}

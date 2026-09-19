import type { Command } from "commander";
import chalk from "chalk";
import ora from "ora";
import { Test0Runtime } from "@test0/core";

export function registerConnectCommand(program: Command): void {
  program
    .command("connect")
    .description("Check connectivity/availability for all registered model providers and configured MCP servers")
    .action(async () => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });

      console.log(chalk.bold("Model providers\n"));
      for (const provider of runtime.gateway.listProviders()) {
        const spinner = ora(`Checking ${provider.displayName}...`).start();
        const available = await provider.checkAvailability();
        if (available) spinner.succeed(`${provider.displayName} (${provider.category})`);
        else spinner.fail(`${provider.displayName} (${provider.category}) — unavailable`);
      }

      const toolCount = runtime.tools.list().filter((t) => t.source === "mcp").length;
      console.log("");
      console.log(chalk.bold("MCP tool sources\n"));
      if (toolCount === 0) {
        console.log(chalk.dim("No external MCP servers configured. Add one under mcpServers: in test0.config.yaml."));
      } else {
        console.log(chalk.green(`✓ ${toolCount} tool(s) available from connected MCP servers`));
      }

      await runtime.shutdown();
    });
}

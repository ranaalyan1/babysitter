import type { Command } from "commander";
import chalk from "chalk";
import { Test0Runtime } from "@test0/core";

export function registerConfigCommand(program: Command): void {
  const cmd = program.command("config").description("View or edit workspace configuration");

  cmd.action(async () => {
    const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
    const config = await runtime.workspace.loadConfig();
    console.log(JSON.stringify(config, null, 2));
  });

  cmd
    .command("permission <scope> <decision>")
    .description("Set a permission rule: allow | ask | block")
    .action(async (scope: string, decision: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      runtime.permissions.setRule(scope, decision as "allow" | "ask" | "block");
      const config = await runtime.workspace.loadConfig();
      config.permissionRules = runtime.permissions.getRules();
      await runtime.workspace.saveConfig(config);
      console.log(chalk.green(`✓ ${scope} -> ${decision}`));
    });
}

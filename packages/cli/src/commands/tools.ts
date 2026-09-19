import type { Command } from "commander";
import chalk from "chalk";
import { Test0Runtime } from "@test0/core";

export function registerToolsCommand(program: Command): void {
  const cmd = program.command("tools").description("List available tools and their permission status");

  cmd.action(async () => {
    const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
    const tools = runtime.tools.list();
    console.log(chalk.bold("AVAILABLE TOOLS\n"));
    for (const t of tools) {
      const check = runtime.permissions.check(t.permissionKey, "cli-inspect");
      const icon = check.decision === "allow" ? chalk.green("✓") : check.decision === "block" ? chalk.red("✗") : chalk.yellow("?");
      console.log(`${icon} ${t.name} [${t.source}] — ${t.description}`);
    }
  });

  cmd
    .command("call <name>")
    .description("Invoke a tool with a JSON args string")
    .option("-a, --args <json>", "JSON-encoded arguments", "{}")
    .action(async (name: string, opts: { args: string }) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const args = JSON.parse(opts.args);
      const result = await runtime.tools.call(name, args, "cli-user");
      console.log(JSON.stringify(result, null, 2));
    });
}

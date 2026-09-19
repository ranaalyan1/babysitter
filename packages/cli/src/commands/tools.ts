import type { Command } from "commander";
import chalk from "chalk";
import Table from "cli-table3";
import { Test0Runtime } from "@test0/core";

export function registerToolsCommand(program: Command): void {
  const cmd = program.command("tools").description("List available tools and their permission status");

  cmd.action(async () => {
    const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
    const tools = runtime.tools.list();

    const table = new Table({
      head: [chalk.bold("Tool"), chalk.bold("Source"), chalk.bold("Permission"), chalk.bold("Description")],
      style: { head: [], border: [] },
      wordWrap: true,
      colWidths: [28, 10, 12, 50],
    });

    for (const t of tools) {
      const check = runtime.permissions.check(t.permissionKey, "cli-inspect");
      const decisionColor = check.decision === "allow" ? chalk.green : check.decision === "block" ? chalk.red : chalk.yellow;
      table.push([t.name, t.source, decisionColor(check.decision), t.description]);
    }

    console.log(table.toString());
    await runtime.shutdown();
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
      await runtime.shutdown();
    });
}

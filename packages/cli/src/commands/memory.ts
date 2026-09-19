import type { Command } from "commander";
import chalk from "chalk";
import { Test0Runtime } from "@test0/core";

export function registerMemoryCommand(program: Command): void {
  const cmd = program.command("memory").description("Inspect or search test0's persistent memory");

  cmd.action(async () => {
    const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
    const records = await runtime.memory.all();
    if (records.length === 0) {
      console.log(chalk.yellow("Memory is empty."));
      return;
    }
    console.log(chalk.bold(`MEMORY (${records.length} records)\n`));
    for (const r of records.slice(-20)) {
      console.log(`- [${r.type}] ${r.key} (updated ${r.updatedAt})`);
    }
  });

  cmd
    .command("search <text>")
    .description("Search memory records")
    .action(async (text: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const results = await runtime.memory.recall({ text });
      console.log(JSON.stringify(results, null, 2));
    });
}

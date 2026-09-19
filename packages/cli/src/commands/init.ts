import type { Command } from "commander";
import chalk from "chalk";
import { Workspace } from "@test0/core";

export function registerInitCommand(program: Command): void {
  program
    .command("init")
    .description("Initialize a test0 workspace in the current directory")
    .option("-n, --name <name>", "project name")
    .action(async (opts: { name?: string }) => {
      const cwd = process.cwd();
      const existing = await Workspace.open(cwd);
      if (existing) {
        console.log(chalk.yellow(`A test0 workspace already exists at ${existing.rootDir}`));
        return;
      }
      const name = opts.name ?? cwd.split("/").filter(Boolean).pop() ?? "project";
      const workspace = await Workspace.init(cwd, name);
      console.log(chalk.green(`✓ Initialized test0 workspace for "${name}"`));
      console.log(`  ${workspace.rootDir}/config.json`);
      console.log(`  ${workspace.rootDir}/memory.json`);
      console.log(`  ${workspace.rootDir}/artifacts/`);
      console.log("");
      console.log("Next steps:");
      console.log(`  ${chalk.cyan("test0 models")}   — see available models`);
      console.log(`  ${chalk.cyan("test0 skills")}   — see installed skills`);
      console.log(`  ${chalk.cyan("test0 run \"<goal>\"")} — run an orchestrated task`);
    });
}

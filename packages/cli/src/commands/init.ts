import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { Command } from "commander";
import chalk from "chalk";
import { Workspace, EXAMPLE_CONFIG_YAML, CONFIG_FILE_NAMES } from "@test0/core";
import { fileExists } from "../util.js";

export function registerInitCommand(program: Command): void {
  program
    .command("init")
    .description("Initialize a test0 workspace in the current directory")
    .option("-n, --name <name>", "project name")
    .option("--with-config", "also write an editable test0.config.yaml")
    .action(async (opts: { name?: string; withConfig?: boolean }) => {
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

      if (opts.withConfig) {
        const alreadyExists = await Promise.all(CONFIG_FILE_NAMES.map((f) => fileExists(join(cwd, f))));
        if (alreadyExists.some(Boolean)) {
          console.log(chalk.yellow("  test0.config.yaml already exists — left untouched"));
        } else {
          const configPath = join(cwd, "test0.config.yaml");
          await writeFile(configPath, EXAMPLE_CONFIG_YAML.replace("my-project", name), "utf-8");
          console.log(`  ${configPath}`);
        }
      }

      console.log("");
      console.log("Next steps:");
      console.log(`  ${chalk.cyan("test0 models")}   — see available models`);
      console.log(`  ${chalk.cyan("test0 skills")}   — see installed skills`);
      console.log(`  ${chalk.cyan('test0 run "<goal>"')} — run an orchestrated task`);
    });
}

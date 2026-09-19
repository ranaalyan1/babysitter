import type { Command } from "commander";
import chalk from "chalk";
import { Test0Runtime } from "@test0/core";

export function registerSkillsCommand(program: Command): void {
  const cmd = program.command("skills").description("List, inspect, install, or remove skills (SKILL.md spec)");

  cmd.action(async () => {
    const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
    const skills = runtime.skills.list();
    if (skills.length === 0) {
      console.log(chalk.yellow("No skills installed. Add a SKILL.md under the skills/ directory."));
      return;
    }
    console.log(chalk.bold("INSTALLED SKILLS\n"));
    for (const s of skills) {
      const errorCount = s.issues.filter((i) => i.level === "error").length;
      const icon = errorCount > 0 ? chalk.red("✗") : chalk.green("✓");
      console.log(`${icon} ${chalk.cyan(s.metadata.name)} (v${s.metadata.version ?? "1.0.0"})`);
      console.log(`    ${s.metadata.description}`);
      if (s.metadata.tags?.length) console.log(chalk.dim(`    tags: ${s.metadata.tags.join(", ")}`));
      if (errorCount > 0) {
        for (const issue of s.issues) {
          console.log(chalk[issue.level === "error" ? "red" : "yellow"](`    [${issue.level}] ${issue.message}`));
        }
      }
    }
  });

  cmd
    .command("show <name>")
    .description("Show a skill's full instructions (Level 2 disclosure)")
    .action(async (name: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const skill = runtime.skills.get(name);
      if (!skill) {
        console.log(chalk.red(`Skill "${name}" not found`));
        return;
      }
      console.log(chalk.bold(`${skill.metadata.name} (v${skill.metadata.version ?? "1.0.0"})\n`));
      console.log(chalk.dim(skill.metadata.description));
      console.log("");
      console.log(skill.instructions);
    });

  cmd
    .command("validate")
    .description("Validate all installed skills against the Agent Skills (SKILL.md) spec")
    .action(async () => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const skills = runtime.skills.list();
      let errorCount = 0;
      for (const s of skills) {
        const errs = s.issues.filter((i) => i.level === "error");
        errorCount += errs.length;
        const icon = errs.length ? chalk.red("✗") : chalk.green("✓");
        console.log(`${icon} ${s.metadata.name || "(unnamed)"}`);
        for (const issue of s.issues) {
          console.log(chalk[issue.level === "error" ? "red" : "yellow"](`    [${issue.level}] ${issue.message}`));
        }
      }
      console.log("");
      console.log(errorCount === 0 ? chalk.green(`All ${skills.length} skill(s) valid.`) : chalk.red(`${errorCount} error(s) found.`));
      process.exitCode = errorCount === 0 ? 0 : 1;
    });
}

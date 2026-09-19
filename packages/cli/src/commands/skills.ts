import type { Command } from "commander";
import chalk from "chalk";
import { Test0Runtime } from "@test0/core";

export function registerSkillsCommand(program: Command): void {
  const cmd = program.command("skills").description("List, inspect, install, or remove skills");

  cmd.action(async () => {
    const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
    const skills = runtime.skills.list();
    if (skills.length === 0) {
      console.log(chalk.yellow("No skills installed. Add a SKILL.md under the skills/ directory."));
      return;
    }
    console.log(chalk.bold("INSTALLED SKILLS\n"));
    for (const s of skills) {
      console.log(`- ${chalk.cyan(s.metadata.name)}@${s.metadata.version} — ${s.metadata.description}`);
      if (s.metadata.tags.length) console.log(`  tags: ${s.metadata.tags.join(", ")}`);
    }
  });

  cmd
    .command("show <name>")
    .description("Show a skill's full instructions")
    .action(async (name: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const skill = runtime.skills.get(name);
      if (!skill) {
        console.log(chalk.red(`Skill "${name}" not found`));
        return;
      }
      console.log(chalk.bold(`${skill.metadata.name}@${skill.metadata.version}\n`));
      console.log(skill.instructions);
    });
}

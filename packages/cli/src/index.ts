#!/usr/bin/env node
import { Command } from "commander";
import { registerInitCommand } from "./commands/init.js";
import { registerModelsCommand } from "./commands/models.js";
import { registerSkillsCommand } from "./commands/skills.js";
import { registerToolsCommand } from "./commands/tools.js";
import { registerAgentsCommand } from "./commands/agents.js";
import { registerMemoryCommand } from "./commands/memory.js";
import { registerRunCommand } from "./commands/run.js";
import { registerConfigCommand } from "./commands/config.js";
import { registerConnectCommand } from "./commands/connect.js";
import { registerTracesCommand } from "./commands/traces.js";
import { registerSafetyCommand } from "./commands/safety.js";

const program = new Command();

program
  .name("test0")
  .description("test0 V5 — Universal Agent Infrastructure CLI")
  .version("5.0.0");

registerInitCommand(program);
registerConnectCommand(program);
registerModelsCommand(program);
registerSkillsCommand(program);
registerToolsCommand(program);
registerAgentsCommand(program);
registerMemoryCommand(program);
registerRunCommand(program);
registerConfigCommand(program);
registerTracesCommand(program);
registerSafetyCommand(program);

program.parseAsync(process.argv).catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
});

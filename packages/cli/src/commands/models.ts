import type { Command } from "commander";
import chalk from "chalk";
import { Test0Runtime } from "@test0/core";

export function registerModelsCommand(program: Command): void {
  const cmd = program.command("models").description("List available models and routing policy");

  cmd.action(async () => {
    const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
    console.log(chalk.bold("AVAILABLE MODELS\n"));
    for (const provider of runtime.gateway.listProviders()) {
      const available = await provider.checkAvailability();
      const models = await provider.listModels();
      const icon = available ? chalk.green("✓") : chalk.red("✗");
      console.log(`${icon} ${provider.displayName}`);
      for (const m of models) {
        const free = m.cost.isFree ? chalk.dim(" (free)") : chalk.dim(` ($${m.cost.inputPerMillion}/$${m.cost.outputPerMillion} per 1M)`);
        console.log(`    - ${m.id}${free}`);
      }
    }
    console.log("");
    console.log(`Routing: ${chalk.cyan("AUTO")}`);
    console.log(`Policy:  ${chalk.cyan(runtime.router.getPolicy().toUpperCase())}`);
  });

  cmd
    .command("set-policy <policy>")
    .description("Set routing policy: free-first | quality-first | local-first | cheapest | fastest")
    .action(async (policy: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const config = await runtime.workspace.loadConfig();
      config.routingPolicy = policy as typeof config.routingPolicy;
      await runtime.workspace.saveConfig(config);
      console.log(chalk.green(`✓ Routing policy set to ${policy}`));
    });
}

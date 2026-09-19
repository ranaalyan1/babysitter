import type { Command } from "commander";
import chalk from "chalk";
import Table from "cli-table3";
import { Test0Runtime } from "@test0/core";

/**
 * Surfaces the Guardrails AI / NeMo-Guardrails-inspired input/output
 * rails (see packages/core/src/guardrails/guardrails.ts) and the
 * GPTCache-inspired response cache (see packages/core/src/cache/) that
 * every routed model call passes through.
 */
export function registerSafetyCommand(program: Command): void {
  const safety = program.command("safety").description("Test the input/output guardrails (prompt-injection, PII, secret redaction)");

  safety
    .command("check <text>")
    .description("Run text through both the input rail (injection) and output rail (PII/secret redaction)")
    .action(async (text: string) => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });

      const input = runtime.guardrails.checkInput(text);
      console.log(chalk.bold("INPUT RAIL (prompt-injection / jailbreak)"));
      console.log(input.safe ? chalk.green("✓ allowed") : chalk.red("✗ blocked"));
      for (const f of input.findings) console.log(`  - ${f.validator}: ${f.detail ?? f.category}`);

      const output = runtime.guardrails.checkOutput(text);
      console.log("\n" + chalk.bold("OUTPUT RAIL (PII / secret redaction)"));
      console.log(output.findings.length ? chalk.yellow(`${output.findings.length} finding(s), redacted`) : chalk.green("✓ clean"));
      for (const f of output.findings) console.log(`  - ${f.validator}: ${f.detail ?? f.category} (${f.count ?? 0} match(es))`);
      if (output.text !== text) {
        console.log("\n" + chalk.bold("Redacted output:"));
        console.log(output.text);
      }
    });

  const cache = program.command("cache").description("Inspect the GPTCache-style response cache");

  cache
    .command("stats", { isDefault: true })
    .description("Show exact/semantic hit-rate stats for the response cache (this process only — the cache is in-memory)")
    .action(async () => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      const stats = runtime.cache.stats();

      const table = new Table({ style: { head: [], border: [] } });
      table.push(
        ["Exact hits", String(stats.exactHits)],
        ["Semantic hits", String(stats.semanticHits)],
        ["Misses", String(stats.misses)],
        ["Hit rate", `${stats.hitRatePercent.toFixed(1)}%`],
        ["Exact cache size", String(stats.exactCacheSize)],
        ["Semantic cache size", String(stats.semanticCacheSize)]
      );
      console.log(table.toString());
      if (stats.exactHits + stats.semanticHits + stats.misses === 0) {
        console.log(
          chalk.yellow(
            "\nNo cache activity yet in this process. The cache is in-memory (GPTCache-style, per-process) — " +
              "run a goal with a repeated/similar prompt inside one `test0 run` to see hits, e.g. via long-running usage of the MCP server."
          )
        );
      }
    });

  cache
    .command("clear")
    .description("Clear the response cache")
    .action(async () => {
      const runtime = await Test0Runtime.load({ projectDir: process.cwd() });
      runtime.cache.clear();
      console.log(chalk.green("✓ Response cache cleared"));
    });
}

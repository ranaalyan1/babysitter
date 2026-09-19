#!/usr/bin/env node
import { Command } from "commander";
import { RepairgateGateway } from "./gateway.js";
import { createDaemon } from "./server/daemon.js";
import { DumbModel, ReliableModel } from "./providers/dumb-model.js";
import { HttpModelBackend } from "./providers/http-backend.js";
import type { ModelBackend } from "./types.js";

const program = new Command();

program.name("repairgate").description("A stateful repair-and-escalation daemon for coding tools + free/weak LLMs").version("0.1.0");

program
  .command("serve")
  .description("Start the daemon: an OpenAI-Chat-Completions-compatible endpoint you point Cursor/Claude Code/Codex at")
  .option("-p, --port <port>", "port to listen on", "8787")
  .option("--demo", "use the built-in deterministic weak/strong demo models instead of a real free-tier API", false)
  .option("--base-url <url>", "OpenAI-compatible base URL for the weakest rung (ignored with --demo)")
  .option("--api-key <key>", "API key for --base-url (ignored with --demo)")
  .option("--model <name>", "model name to request at --base-url (ignored with --demo)")
  .option("--failures-before-escalation <n>", "consecutive step failures before silently bumping to the next rung", "2")
  .action((opts: { port: string; demo: boolean; baseUrl?: string; apiKey?: string; model?: string; failuresBeforeEscalation: string }) => {
    const models: ModelBackend[] = opts.demo
      ? [new DumbModel({ id: "free-weak-model", tier: 0 }), new ReliableModel({ id: "escalation-strong-model", tier: 1 })]
      : buildRealLadder(opts);

    const gateway = new RepairgateGateway({
      ladder: { models, failuresBeforeEscalation: Number(opts.failuresBeforeEscalation) || 2 },
    });

    const port = Number(opts.port) || 8787;
    createDaemon(gateway, { port });

    console.log(`repairgate daemon listening on http://0.0.0.0:${port}/v1/chat/completions`);
    console.log(`Ladder: ${models.map((m) => `${m.id} (tier ${m.tier})`).join(" -> ")}`);
    console.log(opts.demo ? "Running in --demo mode against deterministic simulated models." : "Point your coding tool's base URL here.");
  });

function buildRealLadder(opts: { baseUrl?: string; apiKey?: string; model?: string }): ModelBackend[] {
  if (!opts.baseUrl || !opts.model) {
    console.error("serve: --base-url and --model are required unless --demo is set.");
    process.exit(1);
  }
  return [new HttpModelBackend({ id: opts.model, tier: 0, baseUrl: opts.baseUrl, apiKey: opts.apiKey, model: opts.model })];
}

program.parseAsync(process.argv).catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
});

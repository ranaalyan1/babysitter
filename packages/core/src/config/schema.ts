import type { PermissionDecision, RoutingPolicy } from "../types/index.js";
import type { McpServerConfig } from "../tools/mcp-client.js";

/**
 * Declarative project configuration, modeled directly on LiteLLM's
 * `proxy_config.yaml` (`model_list` + `router_settings` sections) and
 * the MCP ecosystem's `mcpServers` map used by Claude Desktop/Cursor/
 * Claude Code config files. Keeping the same shape as those two widely
 * used formats means test0 configs are easy to read for anyone who has
 * touched either project, and migration in either direction is close to
 * mechanical.
 *
 * This file is meant to be hand-authored and committed to the repo as
 * `test0.config.yaml`; `.test0/config.json` remains the *runtime* state
 * (created by `test0 init`, mutated by commands like `test0 config
 * permission ...`). On `test0 init` / `Test0Runtime.load`, the YAML file
 * (if present) seeds/overrides the runtime config.
 */
export interface Test0FileConfig {
  projectName?: string;

  /** LiteLLM-style routing policy + retry/health knobs. */
  router?: {
    policy?: RoutingPolicy;
    retriesPerCandidate?: number;
    retryBackoffMs?: number;
    health?: {
      allowedFails?: number;
      cooldownMs?: number;
    };
  };

  /** Which built-in model providers to register. Defaults to all. */
  providers?: string[];

  /** Permission overrides, e.g. `{ "terminal.execute": "allow" }`. */
  permissions?: Record<string, PermissionDecision>;

  /** External MCP servers to connect as tool sources, Claude/Cursor-config-style. */
  mcpServers?: Record<string, { command: string; args?: string[]; env?: Record<string, string> }>;

  /** Skill directories to load in addition to the built-in `skills/`. */
  skillPaths?: string[];

  orchestrator?: {
    maxConcurrency?: number;
  };

  /**
   * Per-model rpm/tpm/spend caps, LiteLLM-style. Use "*" to apply a
   * default to every model, and a specific model id to override it.
   */
  budgets?: Record<string, { rpm?: number; tpm?: number; maxBudgetUsd?: number }>;

  /** Record Langfuse/OTel-shaped traces under .test0/traces/traces.jsonl. Default true. */
  tracingEnabled?: boolean;

  /** GPTCache-style exact + semantic response cache in front of the model gateway. */
  cache?: {
    enabled?: boolean;
    ttlMs?: number;
    maxEntries?: number;
    similarityThreshold?: number;
  };

  /** Guardrails AI/NeMo-style input (prompt-injection) and output (PII/secret redaction) checks. */
  guardrails?: {
    enabled?: boolean;
  };
}

export function normalizeMcpServers(config: Test0FileConfig): McpServerConfig[] {
  if (!config.mcpServers) return [];
  return Object.entries(config.mcpServers).map(([id, server]) => ({
    id,
    command: server.command,
    args: server.args,
    env: server.env,
  }));
}

export const EXAMPLE_CONFIG_YAML = `# test0.config.yaml — declarative project configuration.
# Committed to git; .test0/config.json holds runtime state layered on top.

projectName: my-project

router:
  policy: quality-first     # free-first | quality-first | local-first | cheapest | fastest
  retriesPerCandidate: 1
  retryBackoffMs: 200
  health:
    allowedFails: 3         # open the circuit breaker after N consecutive failures
    cooldownMs: 30000       # ...and keep it open this long before retrying

providers:
  - gemini
  - deepseek
  - qwen
  - local-ollama

permissions:
  filesystem.delete: ask
  terminal.execute: ask
  github.createPR: ask
  github.mergePR: ask
  browser.purchase: block

mcpServers: {}
  # github:
  #   command: npx
  #   args: ["-y", "@modelcontextprotocol/server-github"]
  #   env:
  #     GITHUB_PERSONAL_ACCESS_TOKEN: "\${GITHUB_TOKEN}"

skillPaths: []

orchestrator:
  maxConcurrency: 3

# LiteLLM-style per-model rpm/tpm/spend caps. "*" applies to every model;
# a specific model id overrides it. Omit entirely for no enforced limits.
budgets: {}
  # "*":
  #   rpm: 60
  #   tpm: 100000
  # deepseek-r1:
  #   maxBudgetUsd: 5.00

# Record Langfuse/OpenTelemetry-shaped traces under .test0/traces/traces.jsonl
tracingEnabled: true

# GPTCache-style exact + semantic response cache in front of the model
# gateway: identical/near-identical prompts to the same model are served
# without a real call. similarityThreshold is a Jaccard-similarity score
# in [0, 1]; GPTCache's own docs cite ~0.85 as a reasonable default.
cache:
  enabled: true
  ttlMs: 300000
  maxEntries: 500
  similarityThreshold: 0.85

# Guardrails AI/NeMo-Guardrails-style input (prompt-injection/jailbreak)
# and output (PII + secret/credential redaction) checks, run by the
# router on every request/response.
guardrails:
  enabled: true
`;

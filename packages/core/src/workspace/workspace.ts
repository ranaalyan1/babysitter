import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { PermissionRule, RoutingPolicy } from "../types/index.js";
import { DEFAULT_PERMISSION_RULES } from "../security/permissions.js";
import { loadFileConfig } from "../config/loader.js";
import type { Test0FileConfig } from "../config/schema.js";

export interface ModelBudgetConfig {
  rpm?: number;
  tpm?: number;
  maxBudgetUsd?: number;
}

export interface WorkspaceConfig {
  projectName: string;
  routingPolicy: RoutingPolicy;
  permissionRules: PermissionRule[];
  enabledSkills: string[];
  enabledProviders: string[];
  mcpServers: Array<{ id: string; command: string; args?: string[] }>;
  skillPaths: string[];
  orchestrator: { maxConcurrency: number };
  router: { retriesPerCandidate: number; retryBackoffMs: number; allowedFails: number; cooldownMs: number };
  /** Per-model rpm/tpm/spend caps, LiteLLM-style. Keyed by model id; "*" applies to every model. */
  budgets: Record<string, ModelBudgetConfig>;
  /** Whether to record Langfuse/OTel-shaped traces under .test0/traces/. */
  tracingEnabled: boolean;
  /** GPTCache-style exact + semantic response cache in front of the model gateway. */
  cache: { enabled: boolean; ttlMs: number; maxEntries: number; similarityThreshold: number };
  /** Guardrails AI/NeMo-style input (prompt-injection) and output (PII/secret redaction) checks. */
  guardrails: { enabled: boolean };
}

const DEFAULT_CONFIG: Omit<WorkspaceConfig, "projectName"> = {
  routingPolicy: "quality-first",
  permissionRules: DEFAULT_PERMISSION_RULES,
  enabledSkills: [],
  enabledProviders: ["gemini", "deepseek", "qwen", "local-ollama"],
  mcpServers: [],
  skillPaths: [],
  orchestrator: { maxConcurrency: 3 },
  router: { retriesPerCandidate: 1, retryBackoffMs: 200, allowedFails: 3, cooldownMs: 30_000 },
  budgets: {},
  tracingEnabled: true,
  cache: { enabled: true, ttlMs: 5 * 60_000, maxEntries: 500, similarityThreshold: 0.85 },
  guardrails: { enabled: true },
};

/**
 * Workspace (test0 V5 §19): each project gets an isolated `.test0/`
 * directory holding runtime configuration, memory, task history, and
 * artifacts, so test0 behaves like a persistent environment rather than
 * a stateless API call.
 *
 * Configuration is layered, LiteLLM/dotenv-style: defaults <- committed
 * `test0.config.yaml` (if present) <- `.test0/config.json` runtime
 * overrides written by commands like `test0 config permission ...`.
 */
export class Workspace {
  static rootDirName = ".test0";

  private constructor(
    public readonly projectDir: string,
    public readonly rootDir: string,
    public readonly configPath: string,
    public readonly memoryPath: string,
    public readonly artifactsDir: string,
    public readonly taskHistoryPath: string,
    public readonly tracesDir: string
  ) {}

  static paths(projectDir: string) {
    const rootDir = join(projectDir, Workspace.rootDirName);
    return {
      rootDir,
      configPath: join(rootDir, "config.json"),
      memoryPath: join(rootDir, "memory.json"),
      artifactsDir: join(rootDir, "artifacts"),
      taskHistoryPath: join(rootDir, "task-history.json"),
      tracesDir: join(rootDir, "traces"),
    };
  }

  static async init(projectDir: string, projectName: string): Promise<Workspace> {
    const p = Workspace.paths(projectDir);
    await mkdir(p.rootDir, { recursive: true });
    await mkdir(p.artifactsDir, { recursive: true });
    await mkdir(p.tracesDir, { recursive: true });

    const fileConfig = await loadFileConfig(projectDir);
    const config = mergeFileConfig({ projectName, ...DEFAULT_CONFIG }, fileConfig);
    await writeFile(p.configPath, JSON.stringify(config, null, 2), "utf-8");
    await writeFile(p.memoryPath, "[]", "utf-8");
    await writeFile(p.taskHistoryPath, "[]", "utf-8");

    return new Workspace(projectDir, p.rootDir, p.configPath, p.memoryPath, p.artifactsDir, p.taskHistoryPath, p.tracesDir);
  }

  static async open(projectDir: string): Promise<Workspace | undefined> {
    const p = Workspace.paths(projectDir);
    try {
      await readFile(p.configPath, "utf-8");
    } catch {
      return undefined;
    }
    await mkdir(p.artifactsDir, { recursive: true });
    await mkdir(p.tracesDir, { recursive: true });
    return new Workspace(projectDir, p.rootDir, p.configPath, p.memoryPath, p.artifactsDir, p.taskHistoryPath, p.tracesDir);
  }

  async loadConfig(): Promise<WorkspaceConfig> {
    const raw = await readFile(this.configPath, "utf-8");
    const stored = JSON.parse(raw) as Partial<WorkspaceConfig>;
    // Backfill any fields missing from an older `.test0/config.json`
    // (e.g. written by a previous test0 version) with current defaults,
    // so upgrading test0 never crashes on a stale workspace.
    const withDefaults: WorkspaceConfig = {
      ...DEFAULT_CONFIG,
      ...stored,
      projectName: stored.projectName ?? "project",
      orchestrator: { ...DEFAULT_CONFIG.orchestrator, ...stored.orchestrator },
      router: { ...DEFAULT_CONFIG.router, ...stored.router },
      budgets: { ...DEFAULT_CONFIG.budgets, ...stored.budgets },
      cache: { ...DEFAULT_CONFIG.cache, ...stored.cache },
      guardrails: { ...DEFAULT_CONFIG.guardrails, ...stored.guardrails },
    };
    // Re-apply the committed YAML file on every load so editing
    // test0.config.yaml takes effect without re-running `test0 init`,
    // while runtime-only fields (like ad hoc permission grants) persist.
    const fileConfig = await loadFileConfig(this.projectDir);
    return mergeFileConfig(withDefaults, fileConfig);
  }

  async saveConfig(config: WorkspaceConfig): Promise<void> {
    await writeFile(this.configPath, JSON.stringify(config, null, 2), "utf-8");
  }

  async appendTaskHistory(entry: Record<string, unknown>): Promise<void> {
    const history: Record<string, unknown>[] = await readFile(this.taskHistoryPath, "utf-8")
      .then((raw) => JSON.parse(raw))
      .catch(() => []);
    history.push({ ...entry, timestamp: new Date().toISOString() });
    await writeFile(this.taskHistoryPath, JSON.stringify(history, null, 2), "utf-8");
  }
}

function mergeFileConfig(base: WorkspaceConfig, fileConfig: Test0FileConfig | undefined): WorkspaceConfig {
  if (!fileConfig) return base;

  const merged: WorkspaceConfig = {
    ...base,
    projectName: fileConfig.projectName ?? base.projectName,
    routingPolicy: fileConfig.router?.policy ?? base.routingPolicy,
    enabledProviders: fileConfig.providers ?? base.enabledProviders,
    skillPaths: fileConfig.skillPaths ?? base.skillPaths,
    orchestrator: {
      maxConcurrency: fileConfig.orchestrator?.maxConcurrency ?? base.orchestrator.maxConcurrency,
    },
    router: {
      retriesPerCandidate: fileConfig.router?.retriesPerCandidate ?? base.router.retriesPerCandidate,
      retryBackoffMs: fileConfig.router?.retryBackoffMs ?? base.router.retryBackoffMs,
      allowedFails: fileConfig.router?.health?.allowedFails ?? base.router.allowedFails,
      cooldownMs: fileConfig.router?.health?.cooldownMs ?? base.router.cooldownMs,
    },
    mcpServers: fileConfig.mcpServers
      ? Object.entries(fileConfig.mcpServers).map(([id, s]) => ({ id, command: s.command, args: s.args }))
      : base.mcpServers,
    budgets: fileConfig.budgets ?? base.budgets,
    tracingEnabled: fileConfig.tracingEnabled ?? base.tracingEnabled,
    cache: { ...base.cache, ...fileConfig.cache },
    guardrails: { ...base.guardrails, ...fileConfig.guardrails },
  };

  if (fileConfig.permissions) {
    const overrides = new Map(Object.entries(fileConfig.permissions));
    const ruleScopes = new Set(merged.permissionRules.map((r) => r.scope));
    merged.permissionRules = merged.permissionRules.map((r) =>
      overrides.has(r.scope) ? { ...r, decision: overrides.get(r.scope)! } : r
    );
    for (const [scope, decision] of overrides) {
      if (!ruleScopes.has(scope)) merged.permissionRules.push({ scope, decision });
    }
  }

  return merged;
}

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { PermissionRule, RoutingPolicy } from "../types/index.js";
import { DEFAULT_PERMISSION_RULES } from "../security/permissions.js";

export interface WorkspaceConfig {
  projectName: string;
  routingPolicy: RoutingPolicy;
  permissionRules: PermissionRule[];
  enabledSkills: string[];
  enabledProviders: string[];
  mcpServers: Array<{ id: string; command: string; args?: string[] }>;
}

const DEFAULT_CONFIG: Omit<WorkspaceConfig, "projectName"> = {
  routingPolicy: "quality-first",
  permissionRules: DEFAULT_PERMISSION_RULES,
  enabledSkills: [],
  enabledProviders: ["gemini", "deepseek", "qwen", "local-ollama"],
  mcpServers: [],
};

/**
 * Workspace (section 19): each project gets an isolated `.test0/` directory
 * holding configuration, memory, task history, and artifacts, so test0
 * behaves like a persistent environment rather than a stateless API call.
 */
export class Workspace {
  static rootDirName = ".test0";

  private constructor(
    public readonly rootDir: string,
    public readonly configPath: string,
    public readonly memoryPath: string,
    public readonly artifactsDir: string,
    public readonly taskHistoryPath: string
  ) {}

  static paths(projectDir: string) {
    const rootDir = join(projectDir, Workspace.rootDirName);
    return {
      rootDir,
      configPath: join(rootDir, "config.json"),
      memoryPath: join(rootDir, "memory.json"),
      artifactsDir: join(rootDir, "artifacts"),
      taskHistoryPath: join(rootDir, "task-history.json"),
    };
  }

  static async init(projectDir: string, projectName: string): Promise<Workspace> {
    const p = Workspace.paths(projectDir);
    await mkdir(p.rootDir, { recursive: true });
    await mkdir(p.artifactsDir, { recursive: true });

    const config: WorkspaceConfig = { projectName, ...DEFAULT_CONFIG };
    await writeFile(p.configPath, JSON.stringify(config, null, 2), "utf-8");
    await writeFile(p.memoryPath, "[]", "utf-8");
    await writeFile(p.taskHistoryPath, "[]", "utf-8");

    return new Workspace(p.rootDir, p.configPath, p.memoryPath, p.artifactsDir, p.taskHistoryPath);
  }

  static async open(projectDir: string): Promise<Workspace | undefined> {
    const p = Workspace.paths(projectDir);
    try {
      await readFile(p.configPath, "utf-8");
    } catch {
      return undefined;
    }
    await mkdir(p.artifactsDir, { recursive: true });
    return new Workspace(p.rootDir, p.configPath, p.memoryPath, p.artifactsDir, p.taskHistoryPath);
  }

  async loadConfig(): Promise<WorkspaceConfig> {
    const raw = await readFile(this.configPath, "utf-8");
    return JSON.parse(raw);
  }

  async saveConfig(config: WorkspaceConfig): Promise<void> {
    await writeFile(this.configPath, JSON.stringify(config, null, 2), "utf-8");
  }

  async appendTaskHistory(entry: Record<string, unknown>): Promise<void> {
    let history: Record<string, unknown>[] = [];
    try {
      history = JSON.parse(await readFile(this.taskHistoryPath, "utf-8"));
    } catch {
      history = [];
    }
    history.push({ ...entry, timestamp: new Date().toISOString() });
    await writeFile(this.taskHistoryPath, JSON.stringify(history, null, 2), "utf-8");
  }
}

import { join } from "node:path";
import { ModelGateway } from "./models/gateway.js";
import { GeminiProvider } from "./models/providers/gemini.js";
import { DeepSeekProvider } from "./models/providers/deepseek.js";
import { QwenProvider } from "./models/providers/qwen.js";
import { LocalOllamaProvider } from "./models/providers/local-ollama.js";
import { ModelRouter } from "./router/router.js";
import { BenchmarkStore } from "./benchmark/store.js";
import { SkillRegistry } from "./skills/loader.js";
import { ToolGateway } from "./tools/gateway.js";
import { filesystemReadTool, filesystemWriteTool, filesystemListTool } from "./tools/builtin/filesystem.js";
import { terminalRunTool } from "./tools/builtin/terminal.js";
import { PermissionManager } from "./security/permissions.js";
import { MemoryStore } from "./memory/store.js";
import { ContextManager } from "./memory/context.js";
import { Orchestrator } from "./orchestrator/orchestrator.js";
import { Workspace, type WorkspaceConfig } from "./workspace/workspace.js";
import { McpServerConnection } from "./tools/mcp-client.js";
import type { ModelProvider, RoutingPolicy } from "./types/index.js";

export interface Test0RuntimeOptions {
  projectDir: string;
  routingPolicy?: RoutingPolicy;
}

const ALL_BUILTIN_PROVIDERS: Record<string, () => ModelProvider> = {
  gemini: () => new GeminiProvider(),
  deepseek: () => new DeepSeekProvider(),
  qwen: () => new QwenProvider(),
  "local-ollama": () => new LocalOllamaProvider(),
};

/**
 * Test0Runtime wires the full architecture (test0 V5 §2) together:
 * models + skills + tools -> orchestrator -> memory -> workspace.
 * Both the CLI and the MCP server build on top of this single runtime so
 * behavior stays consistent across every entry point.
 */
export class Test0Runtime {
  readonly gateway = new ModelGateway();
  readonly router: ModelRouter;
  readonly benchmarks: BenchmarkStore;
  readonly skills: SkillRegistry;
  readonly tools: ToolGateway;
  readonly permissions: PermissionManager;
  readonly memory: MemoryStore;
  readonly context: ContextManager;
  readonly orchestrator: Orchestrator;
  private readonly mcpConnections: McpServerConnection[] = [];

  private constructor(
    readonly workspace: Workspace,
    config: WorkspaceConfig,
    routingPolicy: RoutingPolicy
  ) {
    for (const providerId of config.enabledProviders) {
      const factory = ALL_BUILTIN_PROVIDERS[providerId];
      if (factory) this.gateway.registerProvider(factory());
    }

    this.benchmarks = new BenchmarkStore(this.gateway);
    this.router = new ModelRouter(this.gateway, {
      policy: routingPolicy,
      benchmarkStore: this.benchmarks,
      retriesPerCandidate: config.router.retriesPerCandidate,
      retryBackoffMs: config.router.retryBackoffMs,
      health: { allowedFails: config.router.allowedFails, cooldownMs: config.router.cooldownMs },
    });

    const skillDirs = [join(workspace.rootDir, "..", "skills"), ...config.skillPaths];
    this.skills = new SkillRegistry(skillDirs);

    this.permissions = new PermissionManager(config.permissionRules);
    this.tools = new ToolGateway(this.permissions);
    this.tools.register(filesystemReadTool);
    this.tools.register(filesystemWriteTool);
    this.tools.register(filesystemListTool);
    this.tools.register(terminalRunTool);

    this.memory = new MemoryStore(workspace.memoryPath);
    this.context = new ContextManager(this.memory);

    this.orchestrator = new Orchestrator(this.router, this.context, this.memory, this.skills, this.tools, {
      projectScope: workspace.rootDir,
      maxConcurrency: config.orchestrator.maxConcurrency,
    });
  }

  static async load(options: Test0RuntimeOptions): Promise<Test0Runtime> {
    let workspace = await Workspace.open(options.projectDir);
    if (!workspace) {
      const name = options.projectDir.split("/").filter(Boolean).pop() ?? "project";
      workspace = await Workspace.init(options.projectDir, name);
    }
    const config = await workspace.loadConfig();
    const runtime = new Test0Runtime(workspace, config, options.routingPolicy ?? config.routingPolicy);
    await runtime.skills.loadAll();
    await runtime.connectConfiguredMcpServers(config);
    return runtime;
  }

  private async connectConfiguredMcpServers(config: WorkspaceConfig): Promise<void> {
    for (const server of config.mcpServers) {
      try {
        const connection = new McpServerConnection(server);
        await connection.connect(this.tools);
        this.mcpConnections.push(connection);
      } catch {
        // A misconfigured/unreachable MCP server should not prevent the
        // rest of test0 from starting; it simply won't contribute tools.
        continue;
      }
    }
  }

  async shutdown(): Promise<void> {
    await Promise.all(this.mcpConnections.map((c) => c.disconnect().catch(() => undefined)));
  }
}

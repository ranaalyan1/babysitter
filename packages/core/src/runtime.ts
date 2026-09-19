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
import { PermissionManager, DEFAULT_PERMISSION_RULES } from "./security/permissions.js";
import { MemoryStore } from "./memory/store.js";
import { ContextManager } from "./memory/context.js";
import { Orchestrator } from "./orchestrator/orchestrator.js";
import { Workspace } from "./workspace/workspace.js";
import type { RoutingPolicy } from "./types/index.js";

export interface Test0RuntimeOptions {
  projectDir: string;
  routingPolicy?: RoutingPolicy;
}

/**
 * Test0Runtime wires the full architecture (section 2) together:
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

  private constructor(
    readonly workspace: Workspace,
    routingPolicy: RoutingPolicy
  ) {
    this.gateway.registerProvider(new GeminiProvider());
    this.gateway.registerProvider(new DeepSeekProvider());
    this.gateway.registerProvider(new QwenProvider());
    this.gateway.registerProvider(new LocalOllamaProvider());

    this.benchmarks = new BenchmarkStore(this.gateway);
    this.router = new ModelRouter(this.gateway, { policy: routingPolicy, benchmarkStore: this.benchmarks });

    this.skills = new SkillRegistry(join(workspace.rootDir, "..", "skills"));

    this.permissions = new PermissionManager(DEFAULT_PERMISSION_RULES);
    this.tools = new ToolGateway(this.permissions);
    this.tools.register(filesystemReadTool);
    this.tools.register(filesystemWriteTool);
    this.tools.register(filesystemListTool);
    this.tools.register(terminalRunTool);

    this.memory = new MemoryStore(workspace.memoryPath);
    this.context = new ContextManager(this.memory);

    this.orchestrator = new Orchestrator(this.router, this.context, this.memory, this.skills, this.tools, {
      projectScope: workspace.rootDir,
    });
  }

  static async load(options: Test0RuntimeOptions): Promise<Test0Runtime> {
    let workspace = await Workspace.open(options.projectDir);
    if (!workspace) {
      const name = options.projectDir.split("/").filter(Boolean).pop() ?? "project";
      workspace = await Workspace.init(options.projectDir, name);
    }
    const config = await workspace.loadConfig();
    const runtime = new Test0Runtime(workspace, options.routingPolicy ?? config.routingPolicy);
    await runtime.skills.loadAll();
    return runtime;
  }
}

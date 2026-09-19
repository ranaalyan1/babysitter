import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import type { ToolExecutor } from "../types/index.js";
import type { ToolGateway } from "./gateway.js";

export interface McpServerConfig {
  id: string;
  command: string;
  args?: string[];
  env?: Record<string, string>;
  /** Permission scope prefix applied to every tool this server exposes. */
  permissionPrefix?: string;
}

/**
 * Connects to an external MCP server (stdio transport) and registers each
 * tool it exposes into test0's ToolGateway, so agents call MCP tools the
 * exact same way they call builtin tools (section 7: "support existing MCP
 * servers instead of rebuilding every integration").
 */
export class McpServerConnection {
  private client?: Client;
  private transport?: StdioClientTransport;

  constructor(private readonly config: McpServerConfig) {}

  async connect(gateway: ToolGateway): Promise<string[]> {
    this.transport = new StdioClientTransport({
      command: this.config.command,
      args: this.config.args ?? [],
      env: this.config.env,
    });
    this.client = new Client({ name: "test0", version: "5.0.0" }, { capabilities: {} });
    await this.client.connect(this.transport);

    const { tools } = await this.client.listTools();
    const registered: string[] = [];

    for (const tool of tools) {
      const namespaced = `${this.config.id}.${tool.name}`;
      const executor: ToolExecutor = {
        name: namespaced,
        descriptor: {
          name: namespaced,
          description: tool.description ?? `Tool "${tool.name}" from MCP server ${this.config.id}`,
          source: "mcp",
          serverId: this.config.id,
          inputSchema: (tool.inputSchema as ToolExecutor["descriptor"]["inputSchema"]) ?? {
            type: "object",
            properties: {},
          },
          permissionKey: `${this.config.permissionPrefix ?? this.config.id}.${tool.name}`,
        },
        execute: async (args) => {
          const start = Date.now();
          const result = await this.client!.callTool({ name: tool.name, arguments: args });
          return {
            ok: !result.isError,
            output: result.content,
            durationMs: Date.now() - start,
          };
        },
      };
      gateway.register(executor);
      registered.push(namespaced);
    }

    return registered;
  }

  async disconnect(): Promise<void> {
    await this.client?.close();
  }
}

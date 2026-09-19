import type { ToolCallResult, ToolDescriptor, ToolExecutor } from "../types/index.js";
import type { PermissionManager } from "../security/permissions.js";

/**
 * Tool Gateway (section 7).
 *
 * Unified discovery + routing layer over builtin tools and external MCP
 * servers. Every tool call is checked against the PermissionManager before
 * executing, and every call (allowed, asked, or blocked) is recorded to the
 * audit log.
 */
export class ToolGateway {
  private tools = new Map<string, ToolExecutor>();

  constructor(private readonly permissions?: PermissionManager) {}

  register(executor: ToolExecutor): void {
    this.tools.set(executor.name, executor);
  }

  unregister(name: string): void {
    this.tools.delete(name);
  }

  list(): ToolDescriptor[] {
    return [...this.tools.values()].map((t) => t.descriptor);
  }

  find(name: string): ToolExecutor | undefined {
    return this.tools.get(name);
  }

  async call(name: string, args: Record<string, unknown>, actor = "agent"): Promise<ToolCallResult> {
    const tool = this.tools.get(name);
    if (!tool) {
      return { ok: false, error: `Unknown tool "${name}"`, durationMs: 0 };
    }

    if (this.permissions) {
      const check = this.permissions.check(tool.descriptor.permissionKey, actor, { tool: name, args });
      if (!check.allowed) {
        return {
          ok: false,
          error: `Permission denied for scope "${check.scope}" (${check.decision}): ${check.reason}`,
          durationMs: 0,
        };
      }
    }

    const start = Date.now();
    try {
      const result = await tool.execute(args);
      return { ...result, durationMs: Date.now() - start };
    } catch (err) {
      return {
        ok: false,
        error: err instanceof Error ? err.message : String(err),
        durationMs: Date.now() - start,
      };
    }
  }
}

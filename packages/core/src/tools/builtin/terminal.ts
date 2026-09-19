import { exec } from "node:child_process";
import { promisify } from "node:util";
import type { ToolExecutor } from "../../types/index.js";

const execAsync = promisify(exec);

export const terminalRunTool: ToolExecutor = {
  name: "terminal.run",
  descriptor: {
    name: "terminal.run",
    description: "Run a shell command in the current workspace and return stdout/stderr.",
    source: "builtin",
    inputSchema: {
      type: "object",
      properties: {
        command: { type: "string" },
        cwd: { type: "string" },
        timeoutMs: { type: "number" },
      },
      required: ["command"],
    },
    permissionKey: "terminal.execute",
  },
  async execute(args) {
    const command = String(args.command);
    const cwd = args.cwd ? String(args.cwd) : process.cwd();
    const timeout = typeof args.timeoutMs === "number" ? args.timeoutMs : 30_000;
    try {
      const { stdout, stderr } = await execAsync(command, { cwd, timeout });
      return { ok: true, output: { stdout, stderr }, durationMs: 0 };
    } catch (err: unknown) {
      const e = err as { stdout?: string; stderr?: string; message?: string };
      return {
        ok: false,
        error: e.message ?? "command failed",
        output: { stdout: e.stdout, stderr: e.stderr },
        durationMs: 0,
      };
    }
  },
};

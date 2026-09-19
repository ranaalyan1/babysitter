import { readFile, writeFile, readdir } from "node:fs/promises";
import type { ToolExecutor } from "../../types/index.js";

export const filesystemReadTool: ToolExecutor = {
  name: "filesystem.read",
  descriptor: {
    name: "filesystem.read",
    description: "Read the contents of a text file in the current workspace.",
    source: "builtin",
    inputSchema: {
      type: "object",
      properties: { path: { type: "string" } },
      required: ["path"],
    },
    permissionKey: "filesystem.read",
  },
  async execute(args) {
    const path = String(args.path);
    const content = await readFile(path, "utf-8");
    return { ok: true, output: content, durationMs: 0 };
  },
};

export const filesystemWriteTool: ToolExecutor = {
  name: "filesystem.write",
  descriptor: {
    name: "filesystem.write",
    description: "Write text content to a file in the current workspace.",
    source: "builtin",
    inputSchema: {
      type: "object",
      properties: { path: { type: "string" }, content: { type: "string" } },
      required: ["path", "content"],
    },
    permissionKey: "filesystem.write",
  },
  async execute(args) {
    const path = String(args.path);
    const content = String(args.content);
    await writeFile(path, content, "utf-8");
    return { ok: true, output: { bytesWritten: content.length }, durationMs: 0 };
  },
};

export const filesystemListTool: ToolExecutor = {
  name: "filesystem.list",
  descriptor: {
    name: "filesystem.list",
    description: "List files in a directory.",
    source: "builtin",
    inputSchema: {
      type: "object",
      properties: { path: { type: "string" } },
      required: ["path"],
    },
    permissionKey: "filesystem.read",
  },
  async execute(args) {
    const path = String(args.path);
    const entries = await readdir(path);
    return { ok: true, output: entries, durationMs: 0 };
  },
};

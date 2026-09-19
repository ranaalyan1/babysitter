#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { Test0Runtime } from "@test0/core";

/**
 * test0 MCP Interface (section 18).
 *
 * Exposes high-level test0 capabilities to any MCP-compatible client
 * (Claude Code, Cursor, Codex, etc.) without forcing the client to
 * understand test0's internals: ask_model, route_task, use_skill,
 * use_tool, delegate_task, search_memory, save_memory, run_agent.
 */
async function main() {
  const projectDir = process.env.TEST0_PROJECT_DIR ?? process.cwd();
  const runtime = await Test0Runtime.load({ projectDir });

  const server = new McpServer({ name: "test0", version: "5.0.0" });

  server.registerTool(
    "ask_model",
    {
      title: "Ask a specific or auto-selected model",
      description:
        "Send a prompt to test0's model gateway. If modelId is omitted, the router auto-selects the best available model for the task type.",
      inputSchema: {
        prompt: z.string(),
        modelId: z.string().optional(),
        taskType: z
          .enum(["coding", "reasoning", "research", "vision", "review", "testing", "planning", "documentation", "general"])
          .optional(),
      },
    },
    async ({ prompt, modelId, taskType }) => {
      if (modelId) {
        const response = await runtime.gateway.complete(modelId, { messages: [{ role: "user", content: prompt }] });
        return textResult(`[${response.provider}/${response.modelId}]\n${response.content}`);
      }
      const { response, decision } = await runtime.router.route(
        { messages: [{ role: "user", content: prompt }], taskType },
        { taskType: taskType ?? "general" }
      );
      return textResult(`[${decision.chosen.displayName}] (policy: ${decision.policy})\n${response.content}`);
    }
  );

  server.registerTool(
    "route_task",
    {
      title: "Get a routing decision for a task",
      description: "Ask the router which model it would use for a given task type and requirements, without executing it.",
      inputSchema: {
        taskType: z.enum(["coding", "reasoning", "research", "vision", "review", "testing", "planning", "documentation", "general"]),
        requireVision: z.boolean().optional(),
        requireToolUse: z.boolean().optional(),
      },
    },
    async ({ taskType, requireVision, requireToolUse }) => {
      const candidates = await runtime.router.selectCandidates({ taskType, requireVision, requireToolUse });
      return textResult(JSON.stringify({ policy: runtime.router.getPolicy(), candidates: candidates.map((c) => c.id) }, null, 2));
    }
  );

  server.registerTool(
    "use_skill",
    {
      title: "Retrieve a skill's instructions",
      description: "Fetch the instructions body of an installed test0 skill by name.",
      inputSchema: { name: z.string() },
    },
    async ({ name }) => {
      const skill = runtime.skills.get(name);
      if (!skill) return textResult(`Skill "${name}" not found. Installed: ${runtime.skills.list().map((s) => s.metadata.name).join(", ") || "(none)"}`, true);
      return textResult(skill.instructions);
    }
  );

  server.registerTool(
    "use_tool",
    {
      title: "Invoke a registered tool",
      description: "Call a builtin or MCP-backed tool registered in test0's tool gateway, subject to permission checks.",
      inputSchema: { name: z.string(), args: z.record(z.string(), z.unknown()).optional() },
    },
    async ({ name, args }) => {
      const result = await runtime.tools.call(name, args ?? {}, "mcp-client");
      return textResult(JSON.stringify(result, null, 2), !result.ok);
    }
  );

  server.registerTool(
    "delegate_task",
    {
      title: "Delegate a complex goal to the orchestrator",
      description:
        "Hand a complex, multi-step goal to test0's orchestrator. test0 plans the steps, assigns specialized agents, selects models/skills/tools, and returns a final report.",
      inputSchema: { goal: z.string() },
    },
    async ({ goal }) => {
      const result = await runtime.orchestrator.run(goal);
      return textResult(result.finalReport);
    }
  );

  server.registerTool(
    "search_memory",
    {
      title: "Search test0's persistent memory",
      description: "Query memory records by type, scope, tags, or free text.",
      inputSchema: {
        text: z.string().optional(),
        type: z.enum(["user", "project", "agent", "task", "conversation", "tool-state"]).optional(),
        scope: z.string().optional(),
        limit: z.number().optional(),
      },
    },
    async ({ text, type, scope, limit }) => {
      const results = await runtime.memory.recall({ text, type, scope, limit });
      return textResult(JSON.stringify(results, null, 2));
    }
  );

  server.registerTool(
    "save_memory",
    {
      title: "Save a memory record",
      description: "Persist a piece of information into test0's memory store for later retrieval.",
      inputSchema: {
        type: z.enum(["user", "project", "agent", "task", "conversation", "tool-state"]),
        scope: z.string(),
        key: z.string(),
        value: z.unknown(),
        tags: z.array(z.string()).optional(),
      },
    },
    async ({ type, scope, key, value, tags }) => {
      const record = await runtime.memory.remember(type, scope, key, value, tags ?? []);
      return textResult(`Saved memory record ${record.id}`);
    }
  );

  server.registerTool(
    "run_agent",
    {
      title: "Run a single specialized agent",
      description: "Run one specialized agent (coder, researcher, reviewer, tester, planner) against a specific instruction.",
      inputSchema: {
        role: z.enum(["planner", "coder", "researcher", "reviewer", "tester", "custom"]),
        instruction: z.string(),
      },
    },
    async ({ role, instruction }) => {
      const result = await runtime.orchestrator.run(`[single-agent:${role}] ${instruction}`);
      return textResult(result.finalReport);
    }
  );

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

function textResult(text: string, isError = false) {
  return { content: [{ type: "text" as const, text }], isError };
}

main().catch((err) => {
  console.error("test0 MCP server failed to start:", err);
  process.exit(1);
});

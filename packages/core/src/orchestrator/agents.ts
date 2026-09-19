import type { AgentDefinition, AgentRole, TaskType } from "../types/index.js";

/**
 * Specialized Agents (section 8).
 *
 * Each agent declares its role, the skills/tools it's expected to draw
 * on, and which task types it prefers — the orchestrator uses this to
 * assign plan steps and to pick sensible routing requirements per step.
 */
export const DEFAULT_AGENTS: AgentDefinition[] = [
  {
    id: "planner-agent",
    role: "planner",
    description: "Breaks down complex goals into structured, dependency-ordered steps.",
    skills: [],
    tools: [],
    preferredTaskTypes: ["planning"],
  },
  {
    id: "coder-agent",
    role: "coder",
    description: "Implements code changes, features, and pipelines.",
    skills: ["python", "javascript", "typescript", "debugging"],
    tools: ["filesystem.read", "filesystem.write", "terminal.run"],
    preferredTaskTypes: ["coding", "documentation"],
  },
  {
    id: "researcher-agent",
    role: "researcher",
    description: "Gathers information, literature, and prior art relevant to the task.",
    skills: ["research", "web-research"],
    tools: [],
    preferredTaskTypes: ["research"],
  },
  {
    id: "reviewer-agent",
    role: "reviewer",
    description: "Reviews implementations for correctness, quality, and security issues.",
    skills: ["code-review", "security"],
    tools: ["filesystem.read"],
    preferredTaskTypes: ["review"],
  },
  {
    id: "tester-agent",
    role: "tester",
    description: "Runs tests and reports failures back to the coder agent.",
    skills: ["debugging"],
    tools: ["terminal.run"],
    preferredTaskTypes: ["testing"],
  },
];

export function findAgentForRole(role: AgentRole, agents: AgentDefinition[] = DEFAULT_AGENTS): AgentDefinition {
  const found = agents.find((a) => a.role === role);
  if (found) return found;
  return {
    id: `${role}-agent`,
    role,
    description: `Generic ${role} agent`,
    skills: [],
    tools: [],
    preferredTaskTypes: ["general"] as TaskType[],
  };
}

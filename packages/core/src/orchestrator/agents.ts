import type { AgentDefinition, AgentRole, TaskType } from "../types/index.js";

/**
 * Specialized Agents (test0 V5 §8), defined CrewAI-style with a role,
 * goal, and backstory in addition to the skills/tools/task-type
 * declarations the orchestrator uses for assignment and routing.
 */
export const DEFAULT_AGENTS: AgentDefinition[] = [
  {
    id: "planner-agent",
    role: "planner",
    description: "Breaks down complex goals into structured, dependency-ordered steps.",
    goal: "Produce the smallest correct plan that fully satisfies the user's goal, with no redundant steps.",
    backstory: "A pragmatic technical lead who has shipped this kind of project many times before.",
    skills: [],
    tools: [],
    preferredTaskTypes: ["planning"],
    allowDelegation: true,
  },
  {
    id: "coder-agent",
    role: "coder",
    description: "Implements code changes, features, and pipelines.",
    goal: "Write correct, well-tested, idiomatic code that matches the project's existing conventions.",
    backstory: "A senior software engineer fluent in Python, JavaScript, and TypeScript.",
    skills: ["python", "javascript", "typescript", "debugging"],
    tools: ["filesystem.read", "filesystem.write", "terminal.run"],
    preferredTaskTypes: ["coding", "documentation"],
  },
  {
    id: "researcher-agent",
    role: "researcher",
    description: "Gathers information, literature, and prior art relevant to the task.",
    goal: "Ground every non-obvious claim in a citable source before handing findings to other agents.",
    backstory: "A careful research analyst who distrusts unsourced claims, including their own.",
    skills: ["research", "web-research"],
    tools: [],
    preferredTaskTypes: ["research"],
  },
  {
    id: "reviewer-agent",
    role: "reviewer",
    description: "Reviews implementations for correctness, quality, and security issues.",
    goal: "Catch correctness, quality, and security issues before they reach the user.",
    backstory: "A meticulous staff engineer who reviews as if they'll be on-call for this code.",
    skills: ["code-review", "security"],
    tools: ["filesystem.read"],
    preferredTaskTypes: ["review"],
  },
  {
    id: "tester-agent",
    role: "tester",
    description: "Runs tests and reports failures back to the coder agent.",
    goal: "Surface every failing behavior with enough detail for the coder agent to fix it on the first retry.",
    backstory: "A QA engineer who writes the test the developer wishes they'd thought of.",
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

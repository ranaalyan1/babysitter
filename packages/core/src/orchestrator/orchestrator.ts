import type {
  AgentDefinition,
  ExecutionPlan,
  OrchestrationResult,
  PlanStep,
  StepResult,
} from "../types/index.js";
import { ModelRouter } from "../router/router.js";
import { ContextManager } from "../memory/context.js";
import { MemoryStore } from "../memory/store.js";
import { SkillRegistry } from "../skills/loader.js";
import { ToolGateway } from "../tools/gateway.js";
import { TaskPlanner } from "./planner.js";
import { DEFAULT_AGENTS, findAgentForRole } from "./agents.js";

export interface OrchestratorOptions {
  agents?: AgentDefinition[];
  projectScope?: string;
}

/**
 * Agent Orchestrator (section 8) implementing the V5 product principle
 * (section 20): the user describes a goal, and test0 determines the plan,
 * agents, skills, tools, models, and execution strategy needed.
 */
export class Orchestrator {
  private readonly agents: AgentDefinition[];
  private readonly projectScope: string;
  private readonly planner = new TaskPlanner();

  constructor(
    private readonly router: ModelRouter,
    private readonly context: ContextManager,
    private readonly memory: MemoryStore,
    private readonly skills: SkillRegistry,
    private readonly tools: ToolGateway,
    options: OrchestratorOptions = {}
  ) {
    this.agents = options.agents ?? DEFAULT_AGENTS;
    this.projectScope = options.projectScope ?? "default";
  }

  async run(goal: string): Promise<OrchestrationResult> {
    const plan = this.planner.plan(goal);
    const stepResults: StepResult[] = [];

    const ready = () =>
      plan.steps.filter(
        (s) => s.status === "pending" && s.dependsOn.every((depId) => plan.steps.find((d) => d.id === depId)?.status === "done")
      );

    // Execute steps respecting dependency order; independent steps could
    // run concurrently, but we keep this sequential for a legible trace.
    let guard = 0;
    while (plan.steps.some((s) => s.status === "pending") && guard < plan.steps.length * 2) {
      guard++;
      const runnable = ready();
      if (runnable.length === 0) break;

      for (const step of runnable) {
        step.status = "in-progress";
        const result = await this.executeStep(step, plan, stepResults);
        stepResults.push(result);
        step.status = result.status === "done" ? "done" : "failed";
      }
    }

    const success = plan.steps.every((s) => s.status === "done");
    const finalReport = this.buildFinalReport(goal, plan, stepResults, success);

    await this.memory.remember(
      "project",
      this.projectScope,
      `goal:${goal.slice(0, 60)}`,
      { goal, success, stepCount: plan.steps.length },
      ["orchestration"]
    );

    return { goal, plan, stepResults, finalReport, success };
  }

  private async executeStep(step: PlanStep, plan: ExecutionPlan, priorResults: StepResult[]): Promise<StepResult> {
    const agent = findAgentForRole(step.assignedRole, this.agents);
    const agentSkills = agent.skills
      .map((name) => this.skills.get(name))
      .filter((s): s is NonNullable<typeof s> => Boolean(s));

    const toolResults: Array<{ tool: string; output: unknown }> = [];
    for (const toolName of agent.tools) {
      if (!this.tools.find(toolName)) continue;
      // Agents only *may* invoke tools relevant to the step; we don't
      // force a call here since not every step needs every declared tool.
    }

    const assembled = await this.context.assemble({
      task: `[${step.assignedRole}] ${step.description}\n\nOverall goal: ${plan.goal}`,
      projectScope: this.projectScope,
      skills: agentSkills,
      toolResults,
      previousAgentResults: priorResults.map((r) => ({ agentId: r.agentId, summary: r.summary })),
    });

    try {
      const { response, decision } = await this.router.route(
        { messages: assembled.messages, taskType: step.taskType },
        { taskType: step.taskType, requireToolUse: agent.tools.length > 0 }
      );

      await this.memory.remember(
        "task",
        this.projectScope,
        `step:${step.id}`,
        { description: step.description, model: decision.chosen.id, summary: response.content },
        ["step-result", step.assignedRole]
      );

      return {
        stepId: step.id,
        agentId: agent.id,
        status: "done",
        summary: response.content,
        modelUsed: decision.chosen.id,
        toolsUsed: agent.tools,
      };
    } catch (err) {
      return {
        stepId: step.id,
        agentId: agent.id,
        status: "failed",
        summary: err instanceof Error ? err.message : String(err),
      };
    }
  }

  private buildFinalReport(goal: string, plan: ExecutionPlan, results: StepResult[], success: boolean): string {
    const lines = [
      `# test0 Orchestration Report`,
      ``,
      `**Goal:** ${goal}`,
      `**Status:** ${success ? "SUCCESS" : "PARTIAL / FAILED"}`,
      ``,
      `## Steps`,
    ];
    for (const step of plan.steps) {
      const result = results.find((r) => r.stepId === step.id);
      lines.push(
        `- [${step.status.toUpperCase()}] (${step.assignedRole}) ${step.description}` +
          (result?.modelUsed ? ` — model: ${result.modelUsed}` : "")
      );
    }
    return lines.join("\n");
  }
}

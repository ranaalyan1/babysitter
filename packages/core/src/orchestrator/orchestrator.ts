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
import { Tracer } from "../observability/tracer.js";

export interface OrchestratorOptions {
  agents?: AgentDefinition[];
  projectScope?: string;
  /** How many independent (dependency-satisfied) steps may run at once. Default 3. */
  maxConcurrency?: number;
  tracer?: Tracer;
}

/**
 * Agent Orchestrator (test0 V5 §8) implementing the V5 product principle
 * (§20): the user describes a goal, and test0 determines the plan,
 * agents, skills, tools, models, and execution strategy needed.
 *
 * Execution follows CrewAI's "sequential process" idea at the dependency
 * level — each step waits for its declared dependencies — but, unlike a
 * strictly linear crew, independent steps (e.g. two research branches
 * with no shared dependency) run concurrently up to `maxConcurrency`,
 * closer to how a real team would parallelize a wave of ready work.
 *
 * Every run is wrapped in a Langfuse/OpenTelemetry-shaped trace: one
 * `orchestration` root span for the whole goal, one `agent` span per
 * plan step, and nested `model` spans (emitted by `ModelRouter`) for
 * every model call inside that step — so a failed or slow run can be
 * inspected span-by-span instead of only reading the final report.
 */
export class Orchestrator {
  private readonly agents: AgentDefinition[];
  private readonly projectScope: string;
  private readonly maxConcurrency: number;
  private readonly planner = new TaskPlanner();
  private readonly tracer?: Tracer;

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
    this.maxConcurrency = options.maxConcurrency ?? 3;
    this.tracer = options.tracer;
  }

  async run(goal: string): Promise<OrchestrationResult> {
    const plan = this.planner.plan(goal);
    const stepResults: StepResult[] = [];
    const trace = this.tracer?.startTrace(`orchestration: ${goal.slice(0, 80)}`, { goal });

    const isSatisfied = (step: PlanStep) =>
      step.dependsOn.every((depId) => plan.steps.find((d) => d.id === depId)?.status === "done");

    const ready = () => plan.steps.filter((s) => s.status === "pending" && isSatisfied(s));

    let guard = 0;
    while (plan.steps.some((s) => s.status === "pending" || s.status === "in-progress") && guard < plan.steps.length * 2) {
      guard++;
      const runnable = ready().slice(0, this.maxConcurrency);
      if (runnable.length === 0) break;

      for (const step of runnable) step.status = "in-progress";

      // Independent, dependency-satisfied steps execute concurrently —
      // there's no reason a research step and an unrelated planning step
      // should serialize just because the orchestrator is sequential
      // about dependency order.
      const results = await Promise.all(runnable.map((step) => this.executeStep(step, plan, stepResults, trace)));

      for (let i = 0; i < runnable.length; i++) {
        const step = runnable[i];
        const result = results[i];
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

    if (trace && this.tracer) await this.tracer.endTrace(trace);

    return { goal, plan, stepResults, finalReport, success, traceId: trace?.id };
  }

  private async executeStep(
    step: PlanStep,
    plan: ExecutionPlan,
    priorResults: StepResult[],
    trace?: import("../observability/tracer.js").Trace
  ): Promise<StepResult> {
    const agent = findAgentForRole(step.assignedRole, this.agents);
    const agentSkills = agent.skills
      .map((name) => this.skills.get(name))
      .filter((s): s is NonNullable<typeof s> => Boolean(s));

    const persona = [agent.backstory, agent.goal ? `Your goal: ${agent.goal}` : undefined].filter(Boolean).join(" ");

    const agentSpan = trace
      ? this.tracer?.startSpan(trace, `${agent.id}: ${step.description}`, "agent", { input: step.description })
      : undefined;

    const assembled = await this.context.assemble({
      task:
        (persona ? `${persona}\n\n` : "") +
        `[${step.assignedRole}] ${step.description}\n\nOverall goal: ${plan.goal}`,
      projectScope: this.projectScope,
      skills: agentSkills,
      previousAgentResults: priorResults.map((r) => ({ agentId: r.agentId, summary: r.summary })),
    });

    try {
      const { response, decision } = await this.router.route(
        { messages: assembled.messages, taskType: step.taskType },
        { taskType: step.taskType, requireToolUse: agent.tools.length > 0 },
        trace ? { trace, parentSpanId: agentSpan?.span.id } : undefined
      );

      await this.memory.remember(
        "task",
        this.projectScope,
        `step:${step.id}`,
        { description: step.description, model: decision.chosen.id, summary: response.content },
        ["step-result", step.assignedRole]
      );

      agentSpan?.end({ output: response.content, attributes: { modelUsed: decision.chosen.id, agentRole: step.assignedRole } });

      return {
        stepId: step.id,
        agentId: agent.id,
        status: "done",
        summary: response.content,
        modelUsed: decision.chosen.id,
        toolsUsed: agent.tools,
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      agentSpan?.end({ error: message, attributes: { agentRole: step.assignedRole } });
      return {
        stepId: step.id,
        agentId: agent.id,
        status: "failed",
        summary: message,
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

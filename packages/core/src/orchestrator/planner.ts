import { randomUUID } from "node:crypto";
import type { AgentRole, ExecutionPlan, PlanStep, TaskType } from "../types/index.js";

/**
 * Task Planning (section 9).
 *
 * Converts a free-form goal into a structured, dependency-ordered plan.
 * This heuristic planner keyword-matches the goal to decide which stages
 * are relevant (a real deployment would ask a reasoning model to produce
 * the plan) — but the *shape* of the plan (dynamic step count, role
 * assignment, dependencies) is what matters for the architecture.
 */
export class TaskPlanner {
  plan(goal: string): ExecutionPlan {
    const lower = goal.toLowerCase();
    const steps: PlanStep[] = [];

    const add = (description: string, role: AgentRole, taskType: TaskType, dependsOn: string[] = []): string => {
      const id = randomUUID();
      steps.push({ id, description, assignedRole: role, dependsOn, taskType, status: "pending" });
      return id;
    };

    const understand = add("Understand requirements and constraints", "planner", "planning");

    let researchId: string | undefined;
    if (/research|paper|literature|study|investigate/.test(lower)) {
      researchId = add("Research relevant methods, prior art, or literature", "researcher", "research", [understand]);
    }

    const design = add("Design architecture / approach", "planner", "planning", researchId ? [researchId] : [understand]);

    let implementId: string | undefined;
    if (/build|implement|create|develop|write.*(code|pipeline|app|application|script)/.test(lower)) {
      implementId = add("Implement the solution", "coder", "coding", [design]);
    }

    let testId: string | undefined;
    if (implementId && /test|pipeline|application|app|script/.test(lower)) {
      testId = add("Run tests against the implementation", "tester", "testing", [implementId]);
      add("Analyze test failures and fix implementation", "coder", "coding", [testId]);
    }

    if (/github|repo|repository/.test(lower)) {
      add("Create/update GitHub repository and push changes", "coder", "coding", implementId ? [implementId] : [design]);
    }

    let securityId: string | undefined;
    if (implementId && /security|secure|vulnerab/.test(lower)) {
      securityId = add("Review implementation for security issues", "reviewer", "review", [implementId]);
    }
    if (implementId) {
      add(
        "Reviewer agent checks implementation quality",
        "reviewer",
        "review",
        testId ? [testId] : securityId ? [securityId] : [implementId]
      );
    }

    if (/document|readme|report/.test(lower) || implementId) {
      add("Generate documentation", "coder", "documentation", implementId ? [implementId] : [design]);
    }

    add("Produce final report", "planner", "planning", steps.length ? [steps[steps.length - 1].id] : [understand]);

    return { goal, steps, createdAt: new Date().toISOString() };
  }
}

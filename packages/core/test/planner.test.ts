import { describe, expect, it } from "vitest";
import { TaskPlanner } from "../src/orchestrator/planner.js";

describe("TaskPlanner", () => {
  it("produces a dynamic, dependency-ordered plan for a full pipeline goal", () => {
    const planner = new TaskPlanner();
    const plan = planner.plan(
      "Build a Python bioinformatics pipeline that analyzes my NGS data, researches relevant papers, implements the pipeline, tests it, and prepares documentation."
    );

    const roles = plan.steps.map((s) => s.assignedRole);
    expect(roles).toContain("researcher");
    expect(roles).toContain("coder");
    expect(roles).toContain("tester");
    expect(roles).toContain("reviewer");

    // Every dependency id must reference a real, earlier step.
    const ids = new Set(plan.steps.map((s) => s.id));
    for (const step of plan.steps) {
      for (const dep of step.dependsOn) {
        expect(ids.has(dep)).toBe(true);
      }
    }
  });

  it("skips research/testing steps for a goal that doesn't need them", () => {
    const planner = new TaskPlanner();
    const plan = planner.plan("Explain how binary search works.");
    const roles = plan.steps.map((s) => s.assignedRole);
    expect(roles).not.toContain("researcher");
    expect(roles).not.toContain("tester");
  });

  it("never produces a circular dependency", () => {
    const planner = new TaskPlanner();
    const plan = planner.plan("Build a GitHub repository with a tested, documented, secure Python app.");
    const indexOf = new Map(plan.steps.map((s, i) => [s.id, i]));
    for (const step of plan.steps) {
      for (const dep of step.dependsOn) {
        expect(indexOf.get(dep)!).toBeLessThan(indexOf.get(step.id)!);
      }
    }
  });
});

import { RepairEngine } from "../repair/engine.js";
import type { Session } from "../session/session.js";
import type { ModelBackend, ModelTurnRequest, RepairedToolCall } from "../types.js";

/**
 * Silent escalation — job #3 from the spec ("free model fails twice on
 * a step → bump *only that step* to a stronger model, invisibly. The
 * tool never knows.").
 *
 * This is a small, deliberately restricted implementation of the
 * FrugalGPT "LLM cascade" idea (Chen et al., 2024 — sequentially query
 * models from cheap to expensive, escalating only when the cheap
 * model's output fails a reliability check) and its descendants
 * (AutoMix, "Cluster, Route, Escalate"): those systems use a learned
 * quality-estimation classifier to *guess* whether an answer is good
 * enough. repairgate doesn't need a classifier, because tool calls are
 * mechanically checkable — the "quality gate" is simply "did it
 * produce a schema-valid tool call (or, when none was required, a
 * plausible final answer) within its nudge-retry budget", exactly the
 * kind of cheap deterministic gate the cost-aware-agent-design
 * literature recommends pairing with cascade routing.
 *
 * Crucially, escalation is scoped to *one step of one session*, not
 * the whole conversation or every future call: `Session.escalate()`
 * only reassigns `assignedModelId` for that `stepId`, so a single hard
 * step (e.g. "write a recursive parser") can borrow a stronger model
 * while every other step in the same task keeps using the free one —
 * this is the "not per-request, task/step-scoped" distinction that a
 * stateless gateway cannot express at all.
 */
export interface EscalationLadder {
  /** Ordered weakest -> strongest. The controller starts every step at ladder[0] unless the session says otherwise. */
  models: ModelBackend[];
  /** Consecutive step failures against the current model before bumping to the next rung. Default 2 (per the spec: "fails twice"). */
  failuresBeforeEscalation?: number;
}

export interface EscalationStepResult {
  success: boolean;
  calls: RepairedToolCall[];
  /** The model id that actually produced the accepted result. */
  modelId: string;
  /** True if this step was served by a model above the ladder's base rung. */
  escalated: boolean;
  attemptsAtThisRung: number;
  totalAttempts: number;
  reason?: string;
}

export class EscalationController {
  private readonly failuresBeforeEscalation: number;

  constructor(
    private readonly ladder: EscalationLadder,
    private readonly repair: RepairEngine = new RepairEngine()
  ) {
    this.failuresBeforeEscalation = ladder.failuresBeforeEscalation ?? 2;
  }

  private modelAt(id: string): ModelBackend {
    const found = this.ladder.models.find((m) => m.id === id);
    if (!found) throw new Error(`Escalation ladder has no model "${id}"`);
    return found;
  }

  private nextRung(currentId: string): ModelBackend | undefined {
    const sorted = [...this.ladder.models].sort((a, b) => a.tier - b.tier);
    const currentTier = this.modelAt(currentId).tier;
    return sorted.find((m) => m.tier > currentTier);
  }

  /**
   * Run one step of a task under a session. The step is retried (with
   * repair nudges, via `RepairEngine.runStep`) against its currently
   * assigned model; on `failuresBeforeEscalation` consecutive
   * *step*-level failures (not merely one bad turn — that's already
   * absorbed by the repair engine's own nudge retries), the session is
   * bumped to the next rung and the step is retried there, invisibly to
   * the caller: the caller only sees the final success/failure and
   * (for observability, not for the calling tool) which model actually
   * answered.
   */
  async runStep(session: Session, stepId: string, request: ModelTurnRequest): Promise<EscalationStepResult> {
    let totalAttempts = 0;
    let step = session.getOrCreateStep(stepId);

    for (;;) {
      const backend = this.modelAt(step.assignedModelId);
      session.recordAttempt(stepId);
      const outcome = await this.repair.runStep(backend, request);
      totalAttempts += outcome.attempts;

      if (outcome.success) {
        session.recordSuccess(stepId);
        return {
          success: true,
          calls: outcome.calls,
          modelId: backend.id,
          escalated: step.escalated,
          attemptsAtThisRung: outcome.attempts,
          totalAttempts,
        };
      }

      step = session.recordFailure(stepId);

      if (step.consecutiveFailures < this.failuresBeforeEscalation) {
        // Not yet time to escalate — the caller may choose to call
        // runStep again (e.g. after the tool's own turn loop advances),
        // but from this controller's perspective this attempt is done.
        return {
          success: false,
          calls: [],
          modelId: backend.id,
          escalated: step.escalated,
          attemptsAtThisRung: outcome.attempts,
          totalAttempts,
          reason: outcome.lastReason,
        };
      }

      const stronger = this.nextRung(step.assignedModelId);
      if (!stronger) {
        // Already at the top of the ladder — nothing left to escalate to.
        return {
          success: false,
          calls: [],
          modelId: backend.id,
          escalated: step.escalated,
          attemptsAtThisRung: outcome.attempts,
          totalAttempts,
          reason: `${outcome.lastReason} (already at strongest model "${backend.id}", no further escalation possible)`,
        };
      }

      session.escalate(stepId, stronger.id, `${step.consecutiveFailures} consecutive failures on "${backend.id}": ${outcome.lastReason}`);
      step = session.getOrCreateStep(stepId);
      // Loop again: retry this same step, now on the stronger model, invisibly to the caller.
    }
  }
}

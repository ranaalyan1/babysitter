import { RepairEngine } from "./repair/engine.js";
import { EscalationController, type EscalationLadder } from "./escalation/controller.js";
import { QuotaOrchestrator, type TaskQuota } from "./quota/orchestrator.js";
import { SessionStore } from "./session/session.js";
import type { ModelBackend, ModelTurnRequest, RepairedToolCall } from "./types.js";

/**
 * The repairgate Gateway: the thin shell (job "3. The thin gateway
 * shell around it") that composes the four real components in the
 * build order the spec lays out — RepairEngine (1), EscalationController
 * (2, which itself wraps RepairEngine), and QuotaOrchestrator (4) — and
 * exposes one method, `handleStep`, that a dialect adapter (job 5) or
 * the HTTP daemon (server/daemon.ts) calls per agent turn.
 *
 * This class intentionally has almost no logic of its own: every real
 * decision (how to repair, when to escalate, whether quota allows the
 * call) lives in its own standalone, independently-tested module. The
 * gateway's only job is sequencing: check quota -> run the step
 * (repair + escalate as needed) -> record quota usage -> hand back a
 * dialect-agnostic result.
 */
export interface GatewayOptions {
  ladder: EscalationLadder;
  quota?: TaskQuota;
  repair?: RepairEngine;
}

export interface HandleStepRequest extends ModelTurnRequest {
  /** Groups steps into one stateful conversation (job #1). Required. */
  sessionId: string;
  /** Identifies this step within the session, for per-step failure/escalation tracking (job #3). Defaults to a counter. */
  stepId?: string;
}

export interface HandleStepResult {
  success: boolean;
  calls: RepairedToolCall[];
  modelId: string;
  escalated: boolean;
  attempts: number;
  reason?: string;
  quotaBlocked?: boolean;
}

export class RepairgateGateway {
  readonly sessions = new SessionStore();
  readonly quota: QuotaOrchestrator;
  private readonly escalation: EscalationController;
  private stepCounters = new Map<string, number>();

  constructor(private readonly options: GatewayOptions) {
    this.quota = new QuotaOrchestrator(options.quota);
    this.escalation = new EscalationController(options.ladder, options.repair ?? new RepairEngine());
  }

  private modelById(id: string): ModelBackend {
    const found = this.options.ladder.models.find((m) => m.id === id);
    if (!found) throw new Error(`No model "${id}" registered on this gateway's ladder`);
    return found;
  }

  private nextStepId(sessionId: string): string {
    const n = (this.stepCounters.get(sessionId) ?? 0) + 1;
    this.stepCounters.set(sessionId, n);
    return `step-${n}`;
  }

  async handleStep(request: HandleStepRequest): Promise<HandleStepResult> {
    const baseModelId = this.options.ladder.models.slice().sort((a, b) => a.tier - b.tier)[0]?.id;
    if (!baseModelId) throw new Error("Escalation ladder has no models configured");

    const session = this.sessions.getOrCreate(request.sessionId, baseModelId);
    const stepId = request.stepId ?? this.nextStepId(request.sessionId);

    const step = session.getOrCreateStep(stepId);
    const estimatedTokens = estimateTokens(request.messages.map((m) => m.content).join("\n"));

    // Task-level quota orchestration (job #4), checked before we even
    // attempt the currently-assigned model for this step.
    const reservation = this.quota.reserve(request.sessionId, step.assignedModelId, estimatedTokens);
    if (!reservation.allowed) {
      // Quota exhausted on the assigned model: let the ladder route
      // around it exactly as it would for a quality failure, per
      // QuotaOrchestrator's design note.
      const candidates = this.options.ladder.models
        .slice()
        .sort((a, b) => a.tier - b.tier)
        .map((m) => m.id);
      const alternative = this.quota.nextAvailableModel(request.sessionId, candidates, estimatedTokens);
      if (!alternative) {
        return { success: false, calls: [], modelId: step.assignedModelId, escalated: step.escalated, attempts: 0, reason: reservation.reason, quotaBlocked: true };
      }
      session.escalate(stepId, alternative, `Quota exhausted on "${step.assignedModelId}": ${reservation.reason}`);
    }

    const result = await this.escalation.runStep(session, stepId, request);

    const backend = this.modelById(result.modelId);
    const usage = request.messages.length > 0 ? estimatedTokens + estimateTokens(JSON.stringify(result.calls)) : estimatedTokens;
    // repairgate doesn't itself know real $ cost for arbitrary backends;
    // callers wiring a real HttpModelBackend should feed actual cost
    // back via quota.record() from their own usage metering if available.
    this.quota.record(request.sessionId, backend.id, usage, 0);

    return {
      success: result.success,
      calls: result.calls,
      modelId: result.modelId,
      escalated: result.escalated,
      attempts: result.totalAttempts,
      reason: result.reason,
    };
  }
}

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

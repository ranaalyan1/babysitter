/**
 * Session state — job #1 from the spec ("it sees the whole
 * conversation, not one request. Gateways are stateless; you are
 * stateful. This is the architectural wall between you and them.").
 *
 * A `Session` tracks, per conversation *and per step within that
 * conversation*, everything a stateless per-request gateway (LiteLLM,
 * Portkey, Bifrost) structurally cannot: how many times a step has
 * failed, which model is currently "assigned" to a step after a silent
 * escalation, and the cumulative token/request usage for the whole
 * task so quota accounting (job #4) can span "an agent firing 25 calls
 * in a row" instead of resetting every request.
 */

export interface StepState {
  stepId: string;
  /** Consecutive repair/validation failures on this step against the currently assigned model. */
  consecutiveFailures: number;
  /** Model id currently assigned to this step; may differ from the session's base model after escalation. */
  assignedModelId: string;
  /** True once this step has been silently bumped to a stronger model at least once. */
  escalated: boolean;
  attempts: number;
}

export interface SessionUsage {
  requests: number;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}

export class Session {
  readonly id: string;
  readonly createdAt: number;
  readonly baseModelId: string;
  private steps = new Map<string, StepState>();
  private usage: SessionUsage = { requests: 0, inputTokens: 0, outputTokens: 0, costUsd: 0 };
  private escalationLog: Array<{ stepId: string; from: string; to: string; reason: string; at: number }> = [];

  constructor(id: string, baseModelId: string, now = Date.now()) {
    this.id = id;
    this.baseModelId = baseModelId;
    this.createdAt = now;
  }

  getOrCreateStep(stepId: string): StepState {
    let step = this.steps.get(stepId);
    if (!step) {
      step = { stepId, consecutiveFailures: 0, assignedModelId: this.baseModelId, escalated: false, attempts: 0 };
      this.steps.set(stepId, step);
    }
    return step;
  }

  recordAttempt(stepId: string): void {
    this.getOrCreateStep(stepId).attempts++;
  }

  recordFailure(stepId: string): StepState {
    const step = this.getOrCreateStep(stepId);
    step.consecutiveFailures++;
    return step;
  }

  recordSuccess(stepId: string): void {
    const step = this.getOrCreateStep(stepId);
    step.consecutiveFailures = 0;
  }

  escalate(stepId: string, toModelId: string, reason: string, now = Date.now()): void {
    const step = this.getOrCreateStep(stepId);
    const from = step.assignedModelId;
    step.assignedModelId = toModelId;
    step.escalated = true;
    step.consecutiveFailures = 0;
    this.escalationLog.push({ stepId, from, to: toModelId, reason, at: now });
  }

  recordUsage(inputTokens: number, outputTokens: number, costUsd: number): void {
    this.usage.requests++;
    this.usage.inputTokens += inputTokens;
    this.usage.outputTokens += outputTokens;
    this.usage.costUsd += costUsd;
  }

  getUsage(): SessionUsage {
    return { ...this.usage };
  }

  getEscalations(): typeof this.escalationLog {
    return [...this.escalationLog];
  }

  getStep(stepId: string): StepState | undefined {
    return this.steps.get(stepId);
  }

  allSteps(): StepState[] {
    return [...this.steps.values()];
  }
}

/** In-memory registry of active sessions, keyed by an id the calling tool controls (e.g. a conversation/task id). */
export class SessionStore {
  private sessions = new Map<string, Session>();

  getOrCreate(sessionId: string, baseModelId: string): Session {
    let session = this.sessions.get(sessionId);
    if (!session) {
      session = new Session(sessionId, baseModelId);
      this.sessions.set(sessionId, session);
    }
    return session;
  }

  get(sessionId: string): Session | undefined {
    return this.sessions.get(sessionId);
  }

  delete(sessionId: string): void {
    this.sessions.delete(sessionId);
  }

  all(): Session[] {
    return [...this.sessions.values()];
  }
}

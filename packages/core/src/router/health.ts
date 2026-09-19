/**
 * Health tracking for routing candidates, modeled after how LiteLLM and
 * OpenRouter keep a router resilient in production:
 *
 *  - LiteLLM's Router marks a deployment "down" after `allowedFails`
 *    consecutive failures and skips it until a cooldown elapses.
 *  - OpenRouter deprioritizes (not permanently removes) any provider
 *    with a "significant outage" in the last 30 seconds, then re-tries
 *    it once the window passes.
 *
 * test0 borrows both ideas: a rolling failure count opens a circuit
 * breaker for a model, and the breaker auto-closes after a cooldown so a
 * transient rate-limit doesn't permanently exile an otherwise-good model.
 */

export interface HealthSnapshot {
  modelId: string;
  consecutiveFailures: number;
  circuitOpenUntil: number | null; // epoch ms, null = closed (healthy)
  lastLatencyMs: number | null;
  avgLatencyMs: number | null;
  totalCalls: number;
  totalFailures: number;
  lastError?: string;
}

export interface HealthTrackerOptions {
  /** Consecutive failures before the circuit opens. Default 3 (LiteLLM default is similar). */
  allowedFails?: number;
  /** How long the circuit stays open before allowing a retry probe. Default 30s (OpenRouter's outage window). */
  cooldownMs?: number;
}

export class HealthTracker {
  private state = new Map<string, HealthSnapshot>();
  private readonly allowedFails: number;
  private readonly cooldownMs: number;

  constructor(options: HealthTrackerOptions = {}) {
    this.allowedFails = options.allowedFails ?? 3;
    this.cooldownMs = options.cooldownMs ?? 30_000;
  }

  private ensure(modelId: string): HealthSnapshot {
    let snapshot = this.state.get(modelId);
    if (!snapshot) {
      snapshot = {
        modelId,
        consecutiveFailures: 0,
        circuitOpenUntil: null,
        lastLatencyMs: null,
        avgLatencyMs: null,
        totalCalls: 0,
        totalFailures: 0,
      };
      this.state.set(modelId, snapshot);
    }
    return snapshot;
  }

  /** True if the circuit is currently open (model should be skipped). */
  isOpen(modelId: string, now = Date.now()): boolean {
    const snapshot = this.state.get(modelId);
    if (!snapshot?.circuitOpenUntil) return false;
    if (now >= snapshot.circuitOpenUntil) {
      // Cooldown elapsed: half-open the circuit for a single probe.
      snapshot.circuitOpenUntil = null;
      return false;
    }
    return true;
  }

  recordSuccess(modelId: string, latencyMs: number): void {
    const snapshot = this.ensure(modelId);
    snapshot.consecutiveFailures = 0;
    snapshot.circuitOpenUntil = null;
    snapshot.lastLatencyMs = latencyMs;
    snapshot.avgLatencyMs =
      snapshot.avgLatencyMs === null ? latencyMs : snapshot.avgLatencyMs * 0.7 + latencyMs * 0.3;
    snapshot.totalCalls += 1;
  }

  recordFailure(modelId: string, error: string, now = Date.now()): void {
    const snapshot = this.ensure(modelId);
    snapshot.consecutiveFailures += 1;
    snapshot.totalCalls += 1;
    snapshot.totalFailures += 1;
    snapshot.lastError = error;
    if (snapshot.consecutiveFailures >= this.allowedFails) {
      snapshot.circuitOpenUntil = now + this.cooldownMs;
    }
  }

  snapshot(modelId: string): HealthSnapshot {
    return { ...this.ensure(modelId) };
  }

  all(): HealthSnapshot[] {
    return [...this.state.values()].map((s) => ({ ...s }));
  }

  reset(modelId?: string): void {
    if (modelId) this.state.delete(modelId);
    else this.state.clear();
  }
}

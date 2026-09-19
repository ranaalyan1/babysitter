import type { AuditLogEntry, PermissionCheckResult, PermissionDecision, PermissionRule } from "../types/index.js";

/**
 * Permission and Security System (section 14).
 *
 * Rules are matched by dotted scope prefix, most-specific wins:
 *   "filesystem.delete" > "filesystem.*" > "*"
 *
 * Every check (allow, ask, block) is written to the audit log — no agent
 * should be able to silently perform a high-impact action.
 */
export class PermissionManager {
  private rules: PermissionRule[] = [];
  private auditLog: AuditLogEntry[] = [];
  private pendingApprovals: Array<{ scope: string; actor: string; detail?: Record<string, unknown> }> = [];

  constructor(initialRules: PermissionRule[] = []) {
    this.rules = [...initialRules];
  }

  setRule(scope: string, decision: PermissionDecision): void {
    const existing = this.rules.find((r) => r.scope === scope);
    if (existing) existing.decision = decision;
    else this.rules.push({ scope, decision });
  }

  getRules(): PermissionRule[] {
    return [...this.rules];
  }

  private resolveDecision(scope: string): { decision: PermissionDecision; matchedScope: string } {
    const parts = scope.split(".");
    for (let i = parts.length; i >= 0; i--) {
      const prefix = i === parts.length ? scope : parts.slice(0, i).join(".") + ".*";
      const rule = this.rules.find((r) => r.scope === prefix);
      if (rule) return { decision: rule.decision, matchedScope: prefix };
    }
    const wildcard = this.rules.find((r) => r.scope === "*");
    if (wildcard) return { decision: wildcard.decision, matchedScope: "*" };
    // Default posture: unknown scopes require explicit approval.
    return { decision: "ask", matchedScope: "(default)" };
  }

  check(scope: string, actor = "agent", detail?: Record<string, unknown>): PermissionCheckResult {
    const { decision, matchedScope } = this.resolveDecision(scope);
    const allowed = decision === "allow";

    if (decision === "ask") {
      this.pendingApprovals.push({ scope, actor, detail });
    }

    this.auditLog.push({
      timestamp: new Date().toISOString(),
      actor,
      scope,
      decision,
      detail,
    });

    return {
      scope,
      decision,
      allowed,
      reason:
        decision === "allow"
          ? `Allowed by rule "${matchedScope}"`
          : decision === "block"
            ? `Blocked by rule "${matchedScope}"`
            : `Requires explicit approval (rule "${matchedScope}")`,
    };
  }

  /** Approve or deny a pending "ask" scope, e.g. from a CLI/UI prompt. */
  resolveApproval(scope: string, approve: boolean, actor = "user"): void {
    this.pendingApprovals = this.pendingApprovals.filter((p) => p.scope !== scope);
    this.setRule(scope, approve ? "allow" : "block");
    this.auditLog.push({
      timestamp: new Date().toISOString(),
      actor,
      scope,
      decision: approve ? "allow" : "block",
      detail: { source: "approval-response" },
    });
  }

  getPendingApprovals() {
    return [...this.pendingApprovals];
  }

  getAuditLog(): AuditLogEntry[] {
    return [...this.auditLog];
  }
}

/** Sensible defaults mirroring the example table in the spec (section 14). */
export const DEFAULT_PERMISSION_RULES: PermissionRule[] = [
  { scope: "filesystem.read", decision: "allow" },
  { scope: "filesystem.write", decision: "allow" },
  { scope: "filesystem.delete", decision: "ask" },
  { scope: "github.read", decision: "allow" },
  { scope: "github.createPR", decision: "ask" },
  { scope: "github.mergePR", decision: "ask" },
  { scope: "browser.navigate", decision: "allow" },
  { scope: "browser.download", decision: "allow" },
  { scope: "browser.purchase", decision: "block" },
  { scope: "terminal.execute", decision: "ask" },
];

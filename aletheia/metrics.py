"""Honest event-derived metrics; no fabricated cost or manual-recovery baseline."""
from __future__ import annotations

from .state import TERMINAL


def metrics(trace: dict) -> dict:
    tasks, events = trace["tasks"], trace["events"]
    terminal = [task for task in tasks if task["state"] in TERMINAL]
    complete = [task for task in tasks if task["state"] == "verified_complete"]
    agent_owned = {event["task_id"] for event in events if event["kind"] == "task.started" and event["payload"].get("adapter") in {"claude-code", "codex", "opencode"}}
    invalid = [event for event in events if event["kind"] == "tool.invalid"]
    repaired = [event for event in events if event["kind"] == "tool.repaired"]
    valid = [event for event in events if event["kind"] == "tool.valid"]
    recovered = [event for event in invalid if any(v["task_id"] == event["task_id"] and v["step_id"] == event["step_id"] and v["seq"] > event["seq"] for v in valid)]
    verified = [event for event in events if event["kind"] == "verification.result"]
    caught = [event for event in verified if event["payload"]["status"] == "failed"]
    escalations = [event for event in events if event["kind"] == "model.escalated"]
    escalated_tasks = {e["task_id"] for e in escalations}
    escalated_steps = {e["step_id"] for e in escalations}
    failures = [e for e in events if e["kind"] == "failure"]
    advanced_steps = {e["payload"]["previous_step_id"] for e in events if e["kind"] == "step.advanced"}
    completed_steps = {e["step_id"] for e in events if e["kind"] == "task.finished" and e["payload"]["state"] == "verified_complete"}
    recovered_steps = {e["step_id"] for e in failures} & (advanced_steps | completed_steps)

    def percentage(n: int, d: int):
        return round(100 * n / d, 2) if d else None

    return {
        "tasks_total": len(tasks), "tasks_terminal": len(terminal), "tasks_verified_complete": len(complete),
        "task_success_rate_percent": percentage(len(complete), len(terminal)),
        "invalid_tool_call_events": len(invalid), "deterministic_repairs": len(repaired),
        "repair_rate_percent": percentage(len(repaired), len(invalid)),
        "invalid_calls_followed_by_valid_call_same_step": len(recovered),
        "tool_call_recovery_rate_percent": percentage(len(recovered), len(invalid)),
        "verification_runs": len(verified), "verification_failures_caught_before_completion": len(caught),
        "verification_catch_rate_percent": percentage(len(caught), len(verified)),
        "escalations": len(escalations), "escalation_rate_percent": percentage(len(escalated_tasks), len(tasks)),
        "recovered_steps_without_escalation": len(recovered_steps - escalated_steps),
        "unnecessary_escalations_avoided": None,
        "tasks_completed_on_base_model_only": sum(t["id"] not in escalated_tasks and t["id"] not in agent_owned for t in complete),
        "tasks_with_agent_owned_model_selection": len(agent_owned),
        "native_escalation_requests": sum(e["kind"] == "escalation.requested" for e in events),
        "tasks_completed_on_weak_or_free_model": None,
        "time_saved_vs_manual_seconds": None,
        "limitations": [
            "Tool recovery means a later valid call in the same step; not proof of semantic equivalence.",
            "Recovered steps without escalation is an observable proxy, not a counterfactual count of unnecessary escalations.",
            "Base-model-only is measured for protocol tasks; native agent model selection, weak/free status and pricing are not inferred.",
            "No manual baseline collected; time saved is unavailable.",
            "Verification proves configured checks, not arbitrary natural-language goal satisfaction.",
        ],
    }

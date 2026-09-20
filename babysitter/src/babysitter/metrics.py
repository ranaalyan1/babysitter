"""Success metrics, computed from the event log — never self-reported.

These are the numbers the brief asks for. Every metric derives from
counted events, so ``babysitter trace --metrics`` shows evidence, not
vibes. Approximations are labeled as such.
"""

from __future__ import annotations

from .schema import (
    KIND_ESCALATION_TRIGGERED,
    KIND_REPAIR_APPLIED,
    KIND_RETRY_QUEUED,
    KIND_VALIDATION_FAILED,
    KIND_VERIFICATION_FAILED,
    KIND_VERIFICATION_PASSED,
    STATUS_FAILED,
    STATUS_ROLLED_BACK,
    STATUS_VERIFIED_COMPLETE,
)
from .store import BabysitterStore


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def task_metrics(store: BabysitterStore, task_id: str) -> dict:
    task = store.get_task(task_id)
    if task is None:
        raise KeyError(f"unknown task: {task_id}")
    malformed = store.count_events(task_id, KIND_VALIDATION_FAILED)
    recovered = store.count_events(task_id, KIND_REPAIR_APPLIED)
    caught = store.count_events(task_id, KIND_VERIFICATION_FAILED)
    passed = store.count_events(task_id, KIND_VERIFICATION_PASSED)
    escalations = store.count_events(task_id, KIND_ESCALATION_TRIGGERED)
    retries = store.count_events(task_id, KIND_RETRY_QUEUED)
    return {
        "task_id": task_id,
        "status": task.status,
        "model": task.model,
        "malformed_tool_calls": malformed,
        "tool_calls_recovered": recovered,
        "repair_rate": _rate(recovered, malformed),
        "verification_failures_caught": caught,
        "verifications_passed": passed,
        "retries_queued": retries,
        "escalations_triggered": escalations,
        # Approximation: retries that resolved without needing escalation.
        "escalations_avoided_approx": max(0, retries - escalations),
    }


def global_metrics(store: BabysitterStore) -> dict:
    tasks = store.list_tasks(limit=10000)
    terminal = [t for t in tasks if t.status in (
        STATUS_VERIFIED_COMPLETE, STATUS_FAILED, STATUS_ROLLED_BACK)]
    completed = [t for t in tasks if t.status == STATUS_VERIFIED_COMPLETE]
    weak_completed = 0
    for task in completed:
        ladder = (task.config or {}).get("ladder") or []
        if ladder and task.model == ladder[0]:
            weak_completed += 1
    agg = {
        "malformed_tool_calls": 0,
        "tool_calls_recovered": 0,
        "verification_failures_caught": 0,
        "retries_queued": 0,
        "escalations_triggered": 0,
    }
    for task in tasks:
        malformed = store.count_events(task.id, KIND_VALIDATION_FAILED)
        recovered = store.count_events(task.id, KIND_REPAIR_APPLIED)
        agg["malformed_tool_calls"] += malformed
        agg["tool_calls_recovered"] += recovered
        agg["verification_failures_caught"] += store.count_events(
            task.id, KIND_VERIFICATION_FAILED)
        agg["retries_queued"] += store.count_events(task.id, KIND_RETRY_QUEUED)
        agg["escalations_triggered"] += store.count_events(
            task.id, KIND_ESCALATION_TRIGGERED)
    return {
        "tasks_total": len(tasks),
        "tasks_terminal": len(terminal),
        "tasks_verified_complete": len(completed),
        "tasks_rolled_back": sum(1 for t in tasks if t.status == STATUS_ROLLED_BACK),
        "tasks_failed": sum(1 for t in tasks if t.status == STATUS_FAILED),
        "task_success_rate": _rate(len(completed), len(terminal)),
        "tasks_completed_on_weak_model": weak_completed,
        **agg,
        "repair_rate": _rate(
            agg["tool_calls_recovered"], agg["malformed_tool_calls"]),
        "escalations_avoided_approx": max(
            0, agg["retries_queued"] - agg["escalations_triggered"]),
    }

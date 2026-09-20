"""Supervised task loop: Observe → Validate → Repair → Execute →
Verify → Recover → Escalate, wired together.

v0.1 task shape: single-step tasks. There is no planner yet, so the whole
task is one step (``step 1``); "consecutive failures on the same step"
means consecutive failures anywhere in the task. Any success resets the
counters. This is the escalation rule applied honestly to v0.1's task
shape — not a shortcut.

Completion rule (evidence over trust): the task completes ONLY when the
model stops calling tools AND verification passes on the final tree.
Model says done + tests fail = retry, not completion. Verification
unavailable = loud terminal failure, never silent success.

Known v0.1 limitation (documented, not hidden): Babysitter proves the
tree is in a verified-good state when the agent stops; it does not judge
whether the goal itself was satisfied. Goal judgment needs an LLM judge,
which is explicitly out of v0.1 scope. The trace records how many files
changed so "completed with 0 changes" is visible, not silent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .classify import FailureEvidence, classify
from .escalate import EscalationManager
from .execute import execute_tool
from .provider import ModelTurn, Provider, ProviderError
from .recover import (
    CheckpointError,
    build_retry_context,
    create_checkpoint,
    restore_checkpoint,
)
from .repair import repair_call
from .schema import (
    KIND_ESCALATION_SKIPPED,
    KIND_ESCALATION_TRIGGERED,
    KIND_FAILURE_CLASSIFIED,
    KIND_MODEL_TURN,
    KIND_REPAIR_APPLIED,
    KIND_REPAIR_FAILED,
    KIND_RETRY_EXHAUSTED,
    KIND_RETRY_QUEUED,
    KIND_TOOL_CALL_OBSERVED,
    KIND_TOOL_ERROR,
    KIND_TOOL_EXECUTED,
    KIND_VALIDATION_FAILED,
    KIND_VALIDATION_PASSED,
    KIND_VERIFICATION_FAILED,
    KIND_VERIFICATION_PASSED,
    KIND_VERIFICATION_STARTED,
    KIND_VERIFICATION_UNAVAILABLE,
    STAGE_ESCALATE,
    STAGE_EXECUTE,
    STAGE_OBSERVE,
    STAGE_RECOVER,
    STAGE_REPAIR,
    STAGE_VALIDATE,
    STAGE_VERIFY,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_ROLLED_BACK,
    STATUS_VERIFIED_COMPLETE,
)
from .store import BabysitterStore
from .toolspec import all_specs
from .validate import validate_call
from .verify import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_UNAVAILABLE,
    VerificationEngine,
    VerificationReport,
)

SYSTEM_PROMPT = """You are a coding agent supervised by Babysitter. Work toward the user's goal by calling tools.
Rules:
- Paths are relative to the project root. Never use absolute paths or ".." escapes.
- Available tools: read_file, write_file, edit_file.
- Make the change, then STOP calling tools so your work can be verified.
- Never claim success yourself; verification decides when the task is done."""


@dataclass
class LoopConfig:
    ladder: list[str]
    verify: dict = field(default_factory=dict)
    max_steps: int = 12
    max_attempts_per_step: int = 3
    escalation_threshold: int = 2


def _tail(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else "…" + text[-limit:]


class TaskLoop:
    def __init__(
        self,
        store: BabysitterStore,
        task_id: str,
        providers: dict[str, Provider],
        config: LoopConfig,
    ) -> None:
        task = store.get_task(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        missing = [m for m in config.ladder if m not in providers]
        if missing:
            raise ValueError(f"no provider configured for ladder models: {missing}")
        self.store = store
        self.task_id = task_id
        self.root = Path(task.project_root)
        self.goal = task.goal
        self.providers = providers
        self.config = config
        self.verify_engine = VerificationEngine(config.verify)
        self.escalation = EscalationManager(
            list(config.ladder), threshold=config.escalation_threshold
        )
        self.touched: list[str] = []
        self.attempt = 0  # consecutive failures on the current step
        self._last_failed_key = ""
        self._repeat_count = 0
        self.history: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task.goal},
        ]

    # -- main loop --------------------------------------------------------

    def run(self) -> str:
        """Run supervision to a terminal status; returns the final status."""
        self.store.set_task_status(self.task_id, STATUS_IN_PROGRESS)
        create_checkpoint(self.store, self.task_id, self.root, "pre-task")
        tools = all_specs()

        for _ in range(self.config.max_steps):
            turn_failed = self._run_turn(tools)
            if turn_failed is None:
                # Terminal status was set inside _run_turn (completed / failed).
                return self.store.get_task(self.task_id).status  # type: ignore[union-attr]
            if not turn_failed:
                self.escalation.note_success()
                self.attempt = 0
                self._repeat_count = 0

        return self._terminal(f"step budget exhausted ({self.config.max_steps} steps)")

    def _run_turn(self, tools: list[dict]) -> bool | None:
        """One model turn. Returns True=failed(retry), False=clean,
        None=terminal status set."""
        provider = self.providers[self.escalation.current_model]
        try:
            turn = provider.complete(self.history, tools)
        except ProviderError as exc:
            return self._fail(
                FailureEvidence(source="provider", tail=str(exc)),
                action_key="provider:call",
                last_action="provider.complete()",
            )
        self.store.log_event(
            self.task_id,
            STAGE_OBSERVE,
            KIND_MODEL_TURN,
            f"model turn ({provider.id}): "
            f"{len(turn.tool_calls)} tool call(s)" if turn.tool_calls else
            f"model turn ({provider.id}): final answer, no tool calls",
            {
                "model": provider.id,
                "step": 1,
                "content_tail": _tail(turn.content or ""),
                "tool_call_count": len(turn.tool_calls),
                "tool_call_names": [c.name for c in turn.tool_calls],
            },
        )
        assistant_msg: dict = {"role": "assistant", "content": turn.content or ""}
        if turn.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": c.call_id or f"call-{i}",
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.args_raw},
                }
                for i, c in enumerate(turn.tool_calls)
            ]
        self.history.append(assistant_msg)

        if not turn.tool_calls:
            return self._finish_if_verified()

        turn_touched: list[str] = []
        for call in turn.tool_calls:
            call_id = call.call_id or "call-?"
            self.store.log_event(
                self.task_id, STAGE_OBSERVE, KIND_TOOL_CALL_OBSERVED,
                f"observed call {call.name}",
                {"call_id": call_id, "name": call.name,
                 "args_raw_tail": _tail(call.args_raw or "")},
            )
            result = validate_call(call.name, call.args_raw, self.root)
            args = result.args
            if not result.ok:
                self.store.log_event(
                    self.task_id, STAGE_VALIDATE, KIND_VALIDATION_FAILED,
                    f"validation failed for {call.name}: "
                    + "; ".join(i.message for i in result.issues)[:200],
                    {"call_id": call_id, "name": call.name,
                     "issues": result.issues_as_dicts()},
                )
                repaired = repair_call(call.name, call.args_raw, self.root)
                if repaired.ok and repaired.args is not None:
                    args = repaired.args
                    self.store.log_event(
                        self.task_id, STAGE_REPAIR, KIND_REPAIR_APPLIED,
                        f"repaired {call.name}: {', '.join(repaired.fixes)}",
                        {"call_id": call_id, "name": call.name,
                         "fixes": repaired.fixes,
                         "args_tail": _tail(json.dumps(args))},
                    )
                else:
                    self.store.log_event(
                        self.task_id, STAGE_REPAIR, KIND_REPAIR_FAILED,
                        f"could not repair {call.name}: {repaired.reason[:200]}",
                        {"call_id": call_id, "name": call.name,
                         "reason": repaired.reason},
                    )
                    issues = "; ".join(i.message for i in result.issues)
                    return self._fail(
                        FailureEvidence(
                            source="loop",
                            tail=f"validation: {issues}\nrepair: {repaired.reason}",
                        ),
                        action_key=f"call:{call.name}",
                        last_action=f"{call.name}({_tail(call.args_raw or '')})",
                    )
            else:
                self.store.log_event(
                    self.task_id, STAGE_VALIDATE, KIND_VALIDATION_PASSED,
                    f"validation passed for {call.name}",
                    {"call_id": call_id, "name": call.name},
                )
            assert args is not None
            exec_result = execute_tool(call.name, args, self.root)
            if exec_result.ok:
                self.store.log_event(
                    self.task_id, STAGE_EXECUTE, KIND_TOOL_EXECUTED,
                    f"executed {call.name} OK",
                    {"call_id": call_id, "name": call.name, "duration_ms": 0,
                     "result_tail": _tail(exec_result.output)},
                )
                turn_touched.extend(exec_result.touched)
                self.history.append(
                    {"role": "tool", "tool_call_id": call_id,
                     "content": exec_result.output}
                )
            else:
                self.store.log_event(
                    self.task_id, STAGE_EXECUTE, KIND_TOOL_ERROR,
                    f"{call.name} failed: {exec_result.error[:200]}",
                    {"call_id": call_id, "name": call.name,
                     "error_tail": _tail(exec_result.error)},
                )
                self.history.append(
                    {"role": "tool", "tool_call_id": call_id,
                     "content": f"ERROR: {exec_result.error}"}
                )
                return self._fail(
                    FailureEvidence(source="tool", tail=exec_result.error),
                    action_key=f"call:{call.name}:{_tail(json.dumps(args, sort_keys=True), 300)}",
                    last_action=f"{call.name}({_tail(json.dumps(args), 300)})",
                )

        if turn_touched:
            for path in turn_touched:
                if path not in self.touched:
                    self.touched.append(path)
            report = self._verify("post-change", turn_touched)
            if report.verdict == VERDICT_PASS:
                checks = ", ".join(c.name for c in report.checks) or "no checks"
                self.history.append(
                    {"role": "user",
                     "content": f"Verification PASSED ({checks}). "
                     "Continue toward the goal, or stop calling tools "
                     "if the goal is achieved."}
                )
                return False
            if report.verdict == VERDICT_FAIL:
                return self._fail(
                    FailureEvidence(
                        source=f"verify-{report.failed_check}",
                        tail=report.tail,
                    ),
                    action_key=f"verify:{report.failed_check}:"
                    + _tail(report.tail, 200),
                    last_action=f"verify after changing {', '.join(turn_touched)}",
                )
            self._terminal(
                f"verification unavailable: {report.unavailable_reason}"
            )
            return None
        return False

    # -- verification ------------------------------------------------------

    def _verify(self, trigger: str, changed: list[str]) -> VerificationReport:
        self.store.log_event(
            self.task_id, STAGE_VERIFY, KIND_VERIFICATION_STARTED,
            f"verification started ({trigger})",
            {"trigger": trigger, "files_changed": list(changed)},
        )
        report = self.verify_engine.run(self.root)
        if report.verdict == VERDICT_PASS:
            self.store.log_event(
                self.task_id, STAGE_VERIFY, KIND_VERIFICATION_PASSED,
                "verification passed",
                report.to_payload(),
            )
        elif report.verdict == VERDICT_FAIL:
            self.store.log_event(
                self.task_id, STAGE_VERIFY, KIND_VERIFICATION_FAILED,
                f"verification failed ({report.failed_check})",
                report.to_payload(),
            )
        else:
            self.store.log_event(
                self.task_id, STAGE_VERIFY, KIND_VERIFICATION_UNAVAILABLE,
                f"verification unavailable: {report.unavailable_reason[:200]}",
                report.to_payload(),
            )
        return report

    def _finish_if_verified(self) -> bool | None:
        """Model stopped calling tools: verify the final tree. Only a PASS
        completes the task."""
        report = self._verify("final", list(self.touched))
        if report.verdict == VERDICT_PASS:
            self.store.set_task_status(
                self.task_id,
                STATUS_VERIFIED_COMPLETE,
                f"verified complete ({len(self.touched)} file(s) changed)",
                {"files_changed": len(self.touched)},
            )
            return None
        if report.verdict == VERDICT_FAIL:
            return self._fail(
                FailureEvidence(
                    source=f"verify-{report.failed_check}", tail=report.tail
                ),
                action_key=f"verify:{report.failed_check}:" + _tail(report.tail, 200),
                last_action="final verification of finished work",
            )
        self._terminal(
            f"verification unavailable: {report.unavailable_reason}"
        )
        return None

    # -- failure / retry / terminal -----------------------------------------

    def _fail(
        self, evidence: FailureEvidence, action_key: str, last_action: str
    ) -> bool | None:
        if action_key == self._last_failed_key:
            self._repeat_count += 1
        else:
            self._last_failed_key = action_key
            self._repeat_count = 1
        evidence.consecutive_repeats = self._repeat_count
        failure_class = classify(evidence)
        self.store.log_event(
            self.task_id, STAGE_RECOVER, KIND_FAILURE_CLASSIFIED,
            f"failure classified as {failure_class}",
            {"class": failure_class, "evidence_tail": _tail(evidence.tail),
             "step": 1},
        )
        decision = self.escalation.note_failure("main")
        if decision.escalate:
            self.store.log_event(
                self.task_id, STAGE_ESCALATE, KIND_ESCALATION_TRIGGERED,
                f"escalated to {decision.to_model} after "
                f"{self.config.escalation_threshold} consecutive failures",
                {"from_model": self.store.get_task(self.task_id).model,  # type: ignore[union-attr]
                 "to_model": decision.to_model, "step": 1,
                 "consecutive_failures": self.config.escalation_threshold},
            )
            self.store.set_task_model(self.task_id, decision.to_model)
            # The stronger model gets a fresh retry budget for the step.
            self.attempt = 0
        elif decision.reason:
            self.store.log_event(
                self.task_id, STAGE_ESCALATE, KIND_ESCALATION_SKIPPED,
                f"escalation skipped: {decision.reason}",
                {"reason": decision.reason, "step": 1},
            )
        self.attempt += 1
        if self.attempt >= self.config.max_attempts_per_step:
            self.store.log_event(
                self.task_id, STAGE_RECOVER, KIND_RETRY_EXHAUSTED,
                f"retry budget exhausted ({self.attempt} attempts)",
                {"step": 1, "attempts": self.attempt},
            )
            self._terminal("retry budget exhausted")
            return None
        context = build_retry_context(
            failure_class, evidence.tail, self.attempt,
            self.config.max_attempts_per_step - 1, last_action,
        )
        self.store.log_event(
            self.task_id, STAGE_RECOVER, KIND_RETRY_QUEUED,
            f"retry queued (attempt {self.attempt})",
            {"step": 1, "attempt": self.attempt,
             "reason_tail": _tail(evidence.tail, 500),
             "model": self.escalation.current_model},
        )
        self.history.append({"role": "user", "content": context})
        return True

    def _terminal(self, reason: str) -> str:
        if self.touched:
            checkpoint = self.store.latest_active_checkpoint(self.task_id)
            if checkpoint is not None:
                try:
                    restore_checkpoint(self.store, checkpoint, self.root)
                except CheckpointError as exc:
                    self.store.set_task_status(
                        self.task_id, STATUS_FAILED,
                        f"failed AND rollback failed: {exc}",
                        {"reason": reason},
                    )
                    return STATUS_FAILED
                self.store.set_task_status(
                    self.task_id, STATUS_ROLLED_BACK,
                    f"{reason}; unverified changes rolled back",
                    {"reason": reason},
                )
                return STATUS_ROLLED_BACK
        self.store.set_task_status(
            self.task_id, STATUS_FAILED, reason, {"reason": reason}
        )
        return STATUS_FAILED


def run_task(
    store: BabysitterStore,
    task_id: str,
    providers: dict[str, Provider],
    config: LoopConfig,
) -> str:
    """Run the supervised loop for a task to a terminal status."""
    return TaskLoop(store, task_id, providers, config).run()

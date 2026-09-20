"""Escalation manager (Escalate stage): one rule, applied honestly.

Rule: ``threshold`` consecutive failures on the SAME step → bump to the
next model on the ladder for that step only. Any success resets the
counter. Moving to a new step resets the counter.

The manager only decides; the loop/server performs the model swap and
writes the ``escalation.triggered`` / ``escalation.skipped`` events.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EscalationDecision:
    escalate: bool
    to_model: str = ""
    reason: str = ""  # set when escalate=False at threshold ("no-stronger-model")


class EscalationManager:
    def __init__(self, ladder: list[str], threshold: int = 2) -> None:
        if not ladder:
            raise ValueError("escalation ladder must list at least one model")
        if threshold < 1:
            raise ValueError("escalation threshold must be >= 1")
        self.ladder = list(ladder)
        self.threshold = threshold
        self.current_model = ladder[0]
        self._step_key: str | None = None
        self._consecutive_failures = 0

    def note_success(self) -> None:
        self._consecutive_failures = 0

    def note_failure(self, step_key: str) -> EscalationDecision:
        """Record a failure on ``step_key``; escalate if it hits threshold."""
        if step_key != self._step_key:
            self._step_key = step_key
            self._consecutive_failures = 0
        self._consecutive_failures += 1
        if self._consecutive_failures < self.threshold:
            return EscalationDecision(escalate=False)
        idx = self.ladder.index(self.current_model)
        if idx >= len(self.ladder) - 1:
            return EscalationDecision(escalate=False, reason="no-stronger-model")
        self.current_model = self.ladder[idx + 1]
        self._consecutive_failures = 0  # the stronger model gets a fresh budget
        return EscalationDecision(escalate=True, to_model=self.current_model)

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

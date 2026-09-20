"""Failure classification (Recover stage, step 1: capture → classify).

Total, deterministic, regex-based. Input is a :class:`FailureEvidence`;
output is always one of the five frozen failure classes. The classifier
never calls a model — it sorts failures so the retry context can tell the
model *what kind* of failure happened, with the raw evidence attached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import (
    FAILURE_NO_PROGRESS_LOOP,
    FAILURE_SYNTAX_FAIL,
    FAILURE_TEST_FAIL,
    FAILURE_TOOL_ERROR,
    FAILURE_UNKNOWN,
)

#: Repeat this same failing action this many times and it is a loop,
#: regardless of the underlying error.
LOOP_THRESHOLD = 3

_SYNTAX_PATTERNS = [
    re.compile(r"SyntaxError", re.IGNORECASE),
    re.compile(r"error TS\d+"),  # tsc
    re.compile(r"unexpected token", re.IGNORECASE),
    re.compile(r"expected .* but (got|found)", re.IGNORECASE),
    re.compile(r"IndentationError"),
    re.compile(r"TabError"),
    re.compile(r"cannot find module", re.IGNORECASE),
    re.compile(r"ModuleNotFoundError"),
    re.compile(r"ImportError"),
    re.compile(r"NameError"),
    re.compile(r"ReferenceError"),
    re.compile(r"TypeError: .* is not a function"),
    re.compile(r"\[eslint\]|ESLint found|had too many (errors|problems)", re.IGNORECASE),
    re.compile(r"^E\d+ ", re.MULTILINE),  # flake8/ruff style codes at line start
    re.compile(r"mypy: .*error", re.IGNORECASE),
    re.compile(r"pyright.*error", re.IGNORECASE),
]


@dataclass
class FailureEvidence:
    """What the classifier gets to look at.

    source: "tool" | "verify-test" | "verify-typecheck" | "provider" | "loop"
    tail: truncated raw output / error text.
    consecutive_repeats: how many times this exact action key just failed
        in a row (tracked by the caller).
    """

    source: str
    tail: str = ""
    consecutive_repeats: int = 0


def classify(evidence: FailureEvidence) -> str:
    if evidence.consecutive_repeats >= LOOP_THRESHOLD:
        return FAILURE_NO_PROGRESS_LOOP
    if evidence.source == "tool":
        # A tool error whose text looks like a syntax problem in the
        # *arguments* (e.g. executor rejected content) is still a tool error:
        # the action failed, not a verification check.
        return FAILURE_TOOL_ERROR
    if evidence.source == "verify-typecheck":
        return FAILURE_SYNTAX_FAIL
    if evidence.source == "verify-test":
        for pattern in _SYNTAX_PATTERNS:
            if pattern.search(evidence.tail or ""):
                return FAILURE_SYNTAX_FAIL
        return FAILURE_TEST_FAIL
    return FAILURE_UNKNOWN

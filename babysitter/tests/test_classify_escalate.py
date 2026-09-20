"""Failure-classification and escalation-rule tests."""

import pytest

from babysitter.classify import FailureEvidence, classify
from babysitter.escalate import EscalationManager
from babysitter.schema import (
    FAILURE_NO_PROGRESS_LOOP,
    FAILURE_SYNTAX_FAIL,
    FAILURE_TEST_FAIL,
    FAILURE_TOOL_ERROR,
    FAILURE_UNKNOWN,
)


def test_tool_source_is_tool_error():
    assert classify(FailureEvidence(source="tool", tail="boom")) == FAILURE_TOOL_ERROR


def test_plain_test_failure():
    assert classify(FailureEvidence(
        source="verify-test", tail="1 failed, 5 passed")) == FAILURE_TEST_FAIL


@pytest.mark.parametrize("tail", [
    "SyntaxError: invalid syntax",
    "src/a.ts(3,1): error TS2322: Type X is not assignable",
    "IndentationError: unexpected indent",
    "ModuleNotFoundError: No module named 'foo'",
    "NameError: name 'x' is not defined",
    "FAIL src/a.test.ts: Cannot find module './missing'",
])
def test_syntax_signals_in_test_output(tail):
    assert classify(FailureEvidence(source="verify-test", tail=tail)) == \
        FAILURE_SYNTAX_FAIL


def test_typecheck_source_is_syntax_fail():
    assert classify(FailureEvidence(source="verify-typecheck", tail="")) == \
        FAILURE_SYNTAX_FAIL


def test_loop_takes_precedence_over_everything():
    assert classify(FailureEvidence(
        source="tool", tail="boom", consecutive_repeats=3)) == \
        FAILURE_NO_PROGRESS_LOOP


def test_two_repeats_is_not_yet_a_loop():
    assert classify(FailureEvidence(
        source="tool", tail="boom", consecutive_repeats=2)) == FAILURE_TOOL_ERROR


def test_unknown_source_falls_back():
    assert classify(FailureEvidence(source="provider", tail="500")) == FAILURE_UNKNOWN


# -- escalation ---------------------------------------------------------------


def test_escalates_after_threshold_consecutive_failures():
    mgr = EscalationManager(["weak", "strong"], threshold=2)
    d1 = mgr.note_failure("main")
    assert not d1.escalate and mgr.current_model == "weak"
    d2 = mgr.note_failure("main")
    assert d2.escalate and d2.to_model == "strong"
    assert mgr.current_model == "strong"
    assert mgr.consecutive_failures == 0  # fresh budget for the stronger model


def test_success_resets_counter():
    mgr = EscalationManager(["weak", "strong"], threshold=2)
    mgr.note_failure("main")
    mgr.note_success()
    d = mgr.note_failure("main")
    assert not d.escalate


def test_new_step_resets_counter():
    mgr = EscalationManager(["weak", "strong"], threshold=2)
    mgr.note_failure("step-a")
    d = mgr.note_failure("step-b")
    assert not d.escalate


def test_top_of_ladder_reports_skipped():
    mgr = EscalationManager(["only"], threshold=1)
    d = mgr.note_failure("main")
    assert not d.escalate and d.reason == "no-stronger-model"


def test_empty_ladder_rejected():
    with pytest.raises(ValueError):
        EscalationManager([], threshold=2)

import json
import sys

import pytest

from aletheia.provider import ProviderError
from aletheia.runtime import SupervisionError, classify
from conftest import answer, call, tool_response

MESSAGES = [{"role": "user", "content": "Fix addition and verify."}]
BAD = "def add(a: int, b: int) -> int:\n    return a - b\n"
GOOD = "def add(a: int, b: int) -> int:\n    return a + b\n"


async def test_defining_demo_repair_fail_rollback_fix_verify(setup_runtime):
    _, store, project, build = setup_runtime
    runtime, provider = build([
        tool_response(call(raw="{path: 'calc.py', content: " + repr(BAD) + ",}")),
        tool_response(call(args={"path": "calc.py", "content": GOOD})), answer("Fixed and verified"),
    ])
    response, task = await runtime.run(MESSAGES, [], {}, protocol="openai", managed=True)
    assert task["state"] == "verified_complete"
    events = store.trace(task["id"])["events"]
    kinds = [event["kind"] for event in events]
    assert "tool.repaired" in kinds and "rollback.completed" in kinds
    evidence = [e["payload"] for e in events if e["kind"] == "verification.result"]
    assert [e["status"] for e in evidence] == ["failed", "passed", "passed"]
    assert (project.root / "calc.py").read_text() == GOOD
    assert "AssertionError" in json.dumps(provider.requests[1]["messages"])
    assert "rolled back" in json.dumps(provider.requests[1]["messages"])
    assert all(r["model"] == "weak" for r in provider.requests)


async def test_two_failures_escalate_only_that_step(setup_runtime):
    _, store, _, build = setup_runtime
    runtime, provider = build([tool_response(call(args={"path": "calc.py", "content": BAD})),
                               tool_response(call(args={"path": "calc.py", "content": BAD + "\n"})),
                               tool_response(call(args={"path": "calc.py", "content": GOOD})), answer()])
    _, task = await runtime.run(MESSAGES, [], {}, protocol="openai", managed=True)
    assert [r["model"] for r in provider.requests] == ["weak", "weak", "strong", "weak"]
    assert task["model"] == "weak"
    assert len([e for e in store.trace()["events"] if e["kind"] == "model.escalated"]) == 1


async def test_unrepairable_missing_field_retries_transparently(setup_runtime):
    _, store, _, build = setup_runtime
    runtime, provider = build([tool_response(call(args={"path": "calc.py"})), tool_response(call()), answer()])
    _, task = await runtime.run(MESSAGES, [], {}, protocol="openai", managed=True)
    assert task["state"] == "verified_complete"
    assert "required" in json.dumps(provider.requests[1]["messages"])
    assert any(e["kind"] == "failure" and e["payload"]["class"] == "tool-error" for e in store.trace()["events"])


async def test_claimed_success_cannot_bypass_failed_tests(setup_runtime):
    config, store, _, build = setup_runtime
    config.test_command = [sys.executable, "-c", "raise AssertionError('not correct')"]
    config.max_attempts = 2
    runtime, _ = build([answer("Everything passed, trust me.")])
    with pytest.raises(SupervisionError, match="budget"):
        await runtime.run(MESSAGES, [], {}, protocol="openai", managed=True)
    assert store.trace()["tasks"][0]["state"] == "failed"
    assert not any(e["payload"].get("state") == "verified_complete" for e in store.trace()["events"])


async def test_missing_verification_is_not_success(setup_runtime):
    config, store, _, build = setup_runtime
    config.typecheck_command = []
    runtime, _ = build([answer()])
    with pytest.raises(SupervisionError, match="unavailable"):
        await runtime.run(MESSAGES, [], {}, protocol="openai", managed=True)
    assert store.trace()["tasks"][0]["state"] == "verification_unavailable"


async def test_no_progress_reads_detected(setup_runtime):
    config, store, _, build = setup_runtime
    config.max_attempts = 5
    runtime, _ = build([tool_response(call("read_file", args={"path": "calc.py"}))])
    with pytest.raises(SupervisionError):
        await runtime.run(MESSAGES, [], {}, protocol="openai", managed=True)
    assert any(e["kind"] == "failure" and e["payload"]["class"] == "no-progress-loop" for e in store.trace()["events"])


async def test_batch_prevalidated_before_any_write(setup_runtime):
    config, store, project, build = setup_runtime
    config.max_attempts = 1
    runtime, _ = build([tool_response(call(args={"path": "calc.py", "content": BAD}), call("missing", call_id="2"))])
    with pytest.raises(SupervisionError):
        await runtime.run(MESSAGES, [], {}, protocol="openai", managed=True)
    assert (project.root / "calc.py").read_text() == GOOD
    assert not any(e["kind"] == "tool.result" for e in store.trace()["events"])


async def test_provider_failures_are_bounded(setup_runtime):
    config, store, _, build = setup_runtime
    config.max_attempts = 2
    runtime, provider = build([ProviderError("offline")])
    with pytest.raises(SupervisionError):
        await runtime.run(MESSAGES, [], {}, protocol="openai")
    assert len(provider.requests) == 2
    assert store.trace()["tasks"][0]["state"] == "failed"


@pytest.mark.parametrize("evidence, expected", [
    ({"commands": [{"name": "test", "exit_code": 1, "stderr": "SyntaxError"}]}, "syntax-fail"),
    ({"commands": [{"name": "test", "exit_code": 1}]}, "test-fail"),
    ({"commands": [{"name": "typecheck", "exit_code": 1}]}, "syntax-fail"),
    ({"status": "unavailable"}, "verification-unavailable"),
])
def test_failure_classes(evidence, expected):
    assert classify(evidence) == expected

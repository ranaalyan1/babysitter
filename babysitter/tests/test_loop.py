"""Supervised-loop tests: the full lifecycle against scripted models
and REAL pytest verification in tmp projects."""

import json
import subprocess
import sys

import pytest

from babysitter.loop import LoopConfig, run_task
from babysitter.provider import (
    ModelTurn,
    ProviderError,
    ScriptedProvider,
    ToolCall,
)
from babysitter.schema import (
    KIND_ESCALATION_TRIGGERED,
    KIND_FAILURE_CLASSIFIED,
    KIND_REPAIR_APPLIED,
    KIND_ROLLBACK_DONE,
    KIND_VERIFICATION_FAILED,
    KIND_VERIFICATION_PASSED,
    STATUS_FAILED,
    STATUS_ROLLED_BACK,
    STATUS_VERIFIED_COMPLETE,
)
from babysitter.store import BabysitterStore

PASS_TEST = "def test_ok():\n    assert True\n"


@pytest.fixture()
def proj(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(PASS_TEST)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    store = BabysitterStore(tmp_path / ".babysitter" / "babysitter.db")
    verify = {"test": [sys.executable, "-m", "pytest", "tests", "-q",
                       "-p", "no:cacheprovider"],
              "timeout_s": 60}
    task = store.create_task("do the thing", str(tmp_path), "weak",
                             {"ladder": ["weak", "strong"]})
    yield store, task, tmp_path, verify
    store.close()


def write_call(call_id, path, content):
    return ToolCall(call_id, "write_file",
                    json.dumps({"path": path, "content": content}))


def test_clean_run_completes(proj):
    store, task, root, verify = proj
    providers = {"weak": ScriptedProvider("weak", [
        ModelTurn("writing", [write_call("c1", "note.txt", "hello")]),
        ModelTurn("done", []),
    ])}
    status = run_task(store, task.id, providers,
                      LoopConfig(ladder=["weak"], verify=verify))
    assert status == STATUS_VERIFIED_COMPLETE
    assert (root / "note.txt").read_text() == "hello"
    assert store.count_events(task.id, KIND_VERIFICATION_PASSED) == 2


def test_malformed_call_is_repaired_transparently(proj):
    store, task, root, verify = proj
    providers = {"weak": ScriptedProvider("weak", [
        ModelTurn("writing", [ToolCall(
            "c1", "write_file",
            '```json\n{"path": "note.txt", "content": "hi",}\n```')]),
        ModelTurn("done", []),
    ])}
    status = run_task(store, task.id, providers,
                      LoopConfig(ladder=["weak"], verify=verify))
    assert status == STATUS_VERIFIED_COMPLETE
    assert (root / "note.txt").read_text() == "hi"
    assert store.count_events(task.id, KIND_REPAIR_APPLIED) == 1


def test_test_failure_feeds_back_and_fix_completes(proj):
    store, task, root, verify = proj
    (root / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n"
    )
    buggy = "VALUE = 41\n"
    fixed_test = ("from widget import VALUE\n\n"
                  "def test_value():\n    assert VALUE == 42\n")
    # NOTE: the fix must change the file SIZE, not just a same-length
    # substitution: CPython validates .pyc caches with integer-second
    # mtimes, so a same-size edit within the same second re-imports stale
    # bytecode. Real agent fixes almost always change size; the demo does.
    providers = {"weak": ScriptedProvider("weak", [
        ModelTurn("writing buggy code", [
            write_call("c1", "widget.py", buggy),
            write_call("c2", "tests/test_widget.py", fixed_test),
        ]),
        ModelTurn("fixing", [ToolCall(
            "c3", "edit_file",
            json.dumps({"path": "widget.py", "old_text": "VALUE = 41\n",
                        "new_text": "VALUE = 42  # the answer\n"}))]),
        ModelTurn("done", []),
    ])}
    status = run_task(store, task.id, providers,
                      LoopConfig(ladder=["weak"], verify=verify))
    assert status == STATUS_VERIFIED_COMPLETE
    assert store.count_events(task.id, KIND_VERIFICATION_FAILED) == 1
    assert store.count_events(task.id, KIND_FAILURE_CLASSIFIED) == 1
    # The retry context the model saw contains the REAL failure output.
    retry = store.list_events(task.id, kinds=["retry.queued"])
    assert len(retry) == 1
    assert "assert 41 == 42" in retry[0].payload["reason_tail"]


def test_two_failures_escalate_to_strong_which_completes(proj):
    store, task, root, verify = proj
    weak = ScriptedProvider("weak", [
        ModelTurn("garbage", [ToolCall("c1", "not_a_tool", "{}")]),
    ])
    strong = ScriptedProvider("strong", [
        ModelTurn("writing", [write_call("c9", "note.txt", "from-strong")]),
        ModelTurn("done", []),
    ])
    status = run_task(store, task.id, {"weak": weak, "strong": strong},
                      LoopConfig(ladder=["weak", "strong"], verify=verify))
    assert status == STATUS_VERIFIED_COMPLETE
    assert store.get_task(task.id).model == "strong"
    assert (root / "note.txt").read_text() == "from-strong"
    triggered = store.list_events(task.id, kinds=[KIND_ESCALATION_TRIGGERED])
    assert len(triggered) == 1
    assert triggered[0].payload["from_model"] == "weak"
    assert triggered[0].payload["to_model"] == "strong"


def test_exhausted_retries_roll_back_changes(proj):
    store, task, root, verify = proj
    providers = {"weak": ScriptedProvider("weak", [
        ModelTurn("writing", [write_call("c1", "junk.txt", "junk")]),
        # Then the model gets stuck deleting nothing and failing:
        ModelTurn("broken", [ToolCall("c2", "not_a_tool", "{}")]),
    ])}
    status = run_task(
        store, task.id, providers,
        LoopConfig(ladder=["weak"], verify=verify, max_attempts_per_step=2))
    assert status == STATUS_ROLLED_BACK
    assert not (root / "junk.txt").exists()  # unverified change reverted
    assert store.count_events(task.id, KIND_ROLLBACK_DONE) == 1


def test_unverifiable_completion_claim_is_rejected(proj):
    """Model says done but no verify commands exist: FAIL, never complete."""
    store, task, root, _ = proj
    providers = {"weak": ScriptedProvider("weak", [ModelTurn("done!", [])])}
    status = run_task(store, task.id, providers,
                      LoopConfig(ladder=["weak"], verify={}))
    assert status == STATUS_FAILED
    unavailable = store.list_events(
        task.id, kinds=["verification.unavailable"])
    assert len(unavailable) == 1


def test_provider_error_is_retried_as_unknown(proj):
    store, task, root, verify = proj

    def flaky(messages, tools, index):
        if index == 0:
            raise ProviderError("connection reset")
        return ModelTurn("done", [])

    providers = {"weak": ScriptedProvider("weak", [flaky])}
    status = run_task(store, task.id, providers,
                      LoopConfig(ladder=["weak"], verify=verify))
    assert status == STATUS_VERIFIED_COMPLETE
    classified = store.list_events(task.id, kinds=[KIND_FAILURE_CLASSIFIED])
    assert classified[0].payload["class"] == "unknown"

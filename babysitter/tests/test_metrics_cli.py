"""Metrics math, CLI commands, and the v0.1 demo as an executable
acceptance test."""

import json
import subprocess
import sys

import pytest

from babysitter.cli import main as cli_main
from babysitter.cli import run_demo
from babysitter.metrics import global_metrics, task_metrics
from babysitter.schema import (
    KIND_ESCALATION_TRIGGERED,
    KIND_REPAIR_APPLIED,
    KIND_RETRY_QUEUED,
    KIND_TASK_STATUS,
    KIND_VALIDATION_FAILED,
    KIND_VERIFICATION_FAILED,
    STAGE_ESCALATE,
    STAGE_OBSERVE,
    STAGE_RECOVER,
    STAGE_REPAIR,
    STAGE_VALIDATE,
    STAGE_VERIFY,
    STATUS_IN_PROGRESS,
    STATUS_VERIFIED_COMPLETE,
)
from babysitter.store import BabysitterStore


@pytest.fixture()
def store(tmp_path):
    s = BabysitterStore(tmp_path / "m.db")
    yield s
    s.close()


def test_task_metrics_math(store):
    task = store.create_task("g", "/tmp", "weak", {"ladder": ["weak"]})
    store.set_task_status(task.id, STATUS_IN_PROGRESS)
    store.log_event(task.id, STAGE_VALIDATE, KIND_VALIDATION_FAILED, "bad",
                    {"call_id": "c", "name": "t", "issues": []})
    store.log_event(task.id, STAGE_VALIDATE, KIND_VALIDATION_FAILED, "bad",
                    {"call_id": "c", "name": "t", "issues": []})
    store.log_event(task.id, STAGE_REPAIR, KIND_REPAIR_APPLIED, "fixed",
                    {"call_id": "c", "name": "t", "fixes": ["x"]})
    store.log_event(task.id, STAGE_VERIFY, KIND_VERIFICATION_FAILED, "fail",
                    {"checks": [], "files_changed": [], "insertions": 0,
                     "deletions": 0, "failed_check": "test", "tail": ""})
    store.log_event(task.id, STAGE_RECOVER, KIND_RETRY_QUEUED, "retry",
                    {"step": 1, "attempt": 1, "reason_tail": "", "model": "weak"})
    store.log_event(task.id, STAGE_ESCALATE, KIND_ESCALATION_TRIGGERED, "esc",
                    {"from_model": "weak", "to_model": "strong", "step": 1,
                     "consecutive_failures": 2})
    store.set_task_status(task.id, STATUS_VERIFIED_COMPLETE)
    m = task_metrics(store, task.id)
    assert m["malformed_tool_calls"] == 2
    assert m["tool_calls_recovered"] == 1
    assert m["repair_rate"] == 0.5
    assert m["verification_failures_caught"] == 1
    assert m["escalations_triggered"] == 1
    assert m["escalations_avoided_approx"] == 0  # 1 retry, 1 escalation


def test_task_metrics_empty_is_none_not_zero_division(store):
    task = store.create_task("g", "/tmp", "weak", {})
    m = task_metrics(store, task.id)
    assert m["repair_rate"] is None


def test_global_metrics_rollup_and_weak_completions(store):
    t1 = store.create_task("g", "/tmp", "weak", {"ladder": ["weak", "strong"]})
    store.set_task_status(t1.id, STATUS_IN_PROGRESS)
    store.set_task_status(t1.id, STATUS_VERIFIED_COMPLETE)
    t2 = store.create_task("g", "/tmp", "strong", {"ladder": ["weak", "strong"]})
    store.set_task_status(t2.id, STATUS_IN_PROGRESS)
    store.set_task_model(t2.id, "strong")
    store.set_task_status(t2.id, STATUS_VERIFIED_COMPLETE)
    g = global_metrics(store)
    assert g["tasks_total"] == 2
    assert g["tasks_verified_complete"] == 2
    assert g["task_success_rate"] == 1.0
    assert g["tasks_completed_on_weak_model"] == 1


# -- CLI ----------------------------------------------------------------------


def test_init_detects_npm_project(tmp_path, capsys):
    (tmp_path / "package.json").write_text(json.dumps(
        {"scripts": {"test": "vitest run", "typecheck": "tsc --noEmit"}}))
    assert cli_main(["init", "--project-root", str(tmp_path)]) == 0
    config = json.loads((tmp_path / "babysitter.json").read_text())
    assert config["verify"]["test"] == ["npm", "test", "--silent"]
    assert config["verify"]["typecheck"] == ["npm", "run", "typecheck", "--silent"]
    assert (tmp_path / ".babysitter" / "babysitter.db").exists()


def test_init_twice_needs_force(tmp_path):
    assert cli_main(["init", "--project-root", str(tmp_path)]) == 0
    assert cli_main(["init", "--project-root", str(tmp_path)]) == 0  # no crash
    assert cli_main(["init", "--project-root", str(tmp_path), "--force"]) == 0


def test_doctor_fails_on_empty_dir(tmp_path, capsys):
    assert cli_main(["doctor", "--project-root", str(tmp_path)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_doctor_passes_on_demo_like_project(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = b'{"object":"list","data":[]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {}}))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    cli_main(["init", "--project-root", str(tmp_path)])
    cfg_path = tmp_path / "babysitter.json"
    config = json.loads(cfg_path.read_text())
    config["verify"]["test"] = ["true"]
    config["provider"]["base_url"] = (
        f"http://127.0.0.1:{server.server_port}/v1")
    cfg_path.write_text(json.dumps(config))
    assert cli_main(["doctor", "--project-root", str(tmp_path)]) == 0
    server.shutdown()


def test_trace_lists_and_shows(tmp_path, capsys):
    cli_main(["init", "--project-root", str(tmp_path)])
    db = tmp_path / ".babysitter" / "babysitter.db"
    store = BabysitterStore(db)
    task = store.create_task("my-goal-here", str(tmp_path), "weak", {})
    store.close()
    assert cli_main(["trace", "--project-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert task.id in out and "my-goal-here" in out
    assert cli_main(["trace", task.id, "--project-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "task.created" in out
    assert cli_main(["trace", task.id, "--metrics",
                     "--project-root", str(tmp_path)]) == 0
    assert cli_main(["trace", "--metrics",
                     "--project-root", str(tmp_path)]) == 0
    assert cli_main(["trace", "bst_nope", "--project-root", str(tmp_path)]) == 1


# -- demo acceptance ------------------------------------------------------------


def test_demo_marks_verified_complete():
    """THE v0.1 demo, automated: weak model fails a tool call -> repair ->
    change -> tests FAIL -> feedback -> fix -> tests PASS -> verified."""
    report = run_demo(quiet=True)
    assert report["status"] == "verified_complete", report
    m = report["metrics"]
    assert m["malformed_tool_calls"] == 2
    assert m["repair_rate"] == 1.0
    assert m["verification_failures_caught"] == 1
    assert m["verifications_passed"] == 2
    assert m["model"] == "demo-weak"  # completed on the WEAK model
    assert report["global_metrics"]["tasks_completed_on_weak_model"] == 1

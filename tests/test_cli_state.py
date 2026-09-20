import json

from babysitter.cli import main
from babysitter.metrics import metrics
from babysitter.state import Store


def test_init_doctor_and_no_overwrite(workspace, capsys):
    assert main(["--root", str(workspace), "init", "--test", "python -m pytest", "--typecheck", "python -m mypy .", "--managed-tools"]) == 0
    assert main(["--root", str(workspace), "init"]) == 1
    capsys.readouterr()
    assert main(["--root", str(workspace), "doctor", "--offline"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]


def test_trace_persists_and_redacts(workspace, capsys):
    store = Store(workspace / ".babysitter")
    task = store.create("test", "weak")
    store.event(task["id"], "observe", "example", {"api_key": "never log this", "message": "Bearer SECRET"}, state="failed")
    store.close()
    assert main(["--root", str(workspace), "trace", task["id"]]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["tasks"][0]["state"] == "failed"
    assert result["events"][0]["payload"] == {"api_key": "[REDACTED]", "message": "Bearer [REDACTED]"}
    assert main(["--root", str(workspace), "trace", "--metrics"]) == 0
    assert json.loads(capsys.readouterr().out)["task_success_rate_percent"] == 0


def test_metrics_do_not_invent_missing_baselines():
    result = metrics({"tasks": [], "events": []})
    assert result["task_success_rate_percent"] is None
    assert result["unnecessary_escalations_avoided"] is None
    assert result["time_saved_vs_manual_seconds"] is None


def test_nonloopback_start_requires_token(workspace, monkeypatch):
    monkeypatch.delenv("BABYSITTER_LOCAL_TOKEN", raising=False)
    assert main(["--root", str(workspace), "start", "--host", "0.0.0.0"]) == 1

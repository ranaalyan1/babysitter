"""Explicitly synthetic presentation fixtures. Never read a real workspace."""
from datetime import datetime, timedelta, timezone

from . import __version__
from .console import AGENTS, summarize
from .state import TERMINAL


def create_demo() -> dict:
    now = datetime.now(timezone.utc)
    cases = [
        ("Handle expired session tokens", "codex", "verified_complete", True),
        ("Add retry budget to native hooks", "claude-code", "recovering", True),
        ("Fix empty tool responses", "opencode", "verified_complete", False),
        ("Validate checkpoint file paths", "codex", "verified_complete", True),
        ("Normalize streamed tool results", "claude-code", "failed", True),
        ("Protect runtime configuration", "opencode", "verified_complete", False),
        ("Repair type errors in the adapter", "codex", "verifying", False),
        ("Update verification command timeout", "claude-code", "verified_complete", False),
    ]
    tasks: list[dict] = []
    details: dict = {}
    checkpoints: dict = {}
    activity: list[dict] = []
    caught = 0
    for i, (goal, agent, state, recovery) in enumerate(cases):
        tid = f"demo-{1084-i}"
        stamp = now - timedelta(minutes=3 + i * 19)
        task = {"id": tid, "session_id": "sample-session-" + str(i), "goal": goal, "state": state, "model": "native:agent-owned",
                "step_id": "sample-step-" + str(i), "attempts": 2 if recovery else 1, "consecutive_failures": int(state in {"failed", "recovering"}),
                "created_at": (stamp - timedelta(minutes=4)).isoformat(), "updated_at": stamp.isoformat(), "plan_json": "[]"}
        events: list[dict] = []
        def add(stage, kind, payload):
            events.append({"seq": i * 30 + len(events), "id": f"sample-event-{i}-{len(events)}", "task_id": tid, "session_id": task["session_id"],
                           "step_id": task["step_id"], "schema_version": 1, "timestamp": (stamp - timedelta(seconds=120-len(events)*10)).isoformat(),
                           "stage": stage, "kind": kind, "attempt": task["attempts"], "model": task["model"], "payload": payload})
        def evidence(passed):
            return {"status": "passed" if passed else "failed", "reason": None if passed else "One or more verification commands failed", "fingerprint": "a8f01d" * 10 + "e124",
                    "files": ["src/runtime.py"], "commands": [
                        {"name": "test", "argv": ["python", "-m", "pytest", "-q"], "exit_code": 0 if passed else 1, "stdout": "42 passed in 1.28s\n" if passed else "FAILED test_expired_session\nAssertionError: expected expired sessions to be rejected\n1 failed, 41 passed in 1.12s\n", "stderr": "", "duration_seconds": 1.28, "timed_out": False},
                        {"name": "typecheck", "argv": ["python", "-m", "mypy", "src"], "exit_code": 0, "stdout": "Success: no issues found in 8 source files\n", "stderr": "", "duration_seconds": .62, "timed_out": False},
                        {"name": "git-diff", "argv": ["git", "diff", "--check", "HEAD"], "exit_code": 0, "stdout": "", "stderr": "", "duration_seconds": .01, "timed_out": False}]}
        add("observe", "task.started", {"adapter": agent, "goal": goal, "demo": True})
        cps = []
        for purpose in (["baseline", "failed_changes"] if recovery else ["baseline"]):
            cid = f"sample-{i}-{purpose}"
            cp = {"id": cid, "task_id": tid, "purpose": purpose, "created_at": task["created_at"]}
            cps.append(cp)
            checkpoints[(tid, cid)] = {**cp, "files": [{"path": n, "sha256": "e7d9a0" * 10 + "abcd", "mode": 420, "symlink": False} for n in ["src/runtime.py", "tests/test_runtime.py", "pyproject.toml"]], "truncated": False}
        task["checkpoint_id"] = cps[0]["id"]
        add("execute", "checkpoint.created", {"checkpoint_id": cps[0]["id"], "purpose": "baseline"})
        add("validate", "tool.valid", {"tool": "apply_patch" if agent == "codex" else "write", "scope": "Illustrative native observation"})
        add("execute", "tool.result", {"tool": "write", "result": "Updated src/runtime.py", "error": False})
        if recovery:
            caught += 1
            add("verify", "verification.result", evidence(False))
            add("execute", "checkpoint.created", {"checkpoint_id": cps[1]["id"], "purpose": "failed_changes"})
            add("recover", "rollback.completed", {"baseline_id": cps[0]["id"], "reason": "Failed contents retained before restoring baseline"})
            add("recover", "retry.scheduled", {"instruction": "Reapply a corrected patch. Fix the failed assertion before completing.", "next_model": "agent-owned"})
        if state == "verified_complete":
            add("verify", "verification.result", evidence(True))
            add("observe", "task.finished", {"state": state, "adapter": agent})
        elif state == "failed":
            add("observe", "task.finished", {"state": "failed", "reason": "Recovery budget exhausted; inspect retained checkpoints"})
        elif state == "verifying":
            add("verify", "verification.started", {"adapter": agent})
        summary = summarize(task, events, cps)
        tasks.append(summary)
        details[tid] = {"schema_version": 1, "task": summary, "events": events, "events_truncated": False, "checkpoints": cps}
        activity.extend(e for e in events if e["kind"] in {"task.finished", "verification.result", "rollback.completed", "retry.scheduled"})
    return {"workspace": {"mode": "demo", "version": __version__, "project": "aletheia", "root": "Sample workspace · no real repository connected",
             "stats": {"total": len(tasks), "verified": sum(t["state"] == "verified_complete" for t in tasks), "active": sum(t["state"] not in TERMINAL for t in tasks),
                       "failed": sum(t["state"] == "failed" for t in tasks), "caught": caught, "checkpoints": len(checkpoints)},
             "tasks": tasks, "tasks_truncated": False, "activity": sorted(activity, key=lambda e: e["timestamp"], reverse=True)[:8],
             "config": {"initialized": True, "commands": {"test": ["python", "-m", "pytest", "-q"], "typecheck": ["python", "-m", "mypy", "src"]}, "error": None},
             "agents": [{**a, "observed": True} for a in AGENTS]}, "details": details, "checkpoints": checkpoints}

"""Protocol-server tests: both adapters, transparent repair,
between-turn verification, escalation — all through real HTTP."""

import json

import pytest
from fastapi.testclient import TestClient

from babysitter.provider import ModelTurn, ScriptedProvider, ToolCall
from babysitter.schema import (
    KIND_ESCALATION_TRIGGERED,
    KIND_REPAIR_APPLIED,
    KIND_VALIDATION_FAILED,
    KIND_VERIFICATION_FAILED,
)
from babysitter.server import ServerConfig, create_app
from babysitter.store import BabysitterStore

AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "write_note",
        "description": "Write a note.",
        "parameters": {
            "type": "object",
            "required": ["path", "content"],
            "properties": {"path": {"type": "string"},
                           "content": {"type": "string"}},
        },
    },
}


@pytest.fixture()
def harness(tmp_path):
    """A server supervising a tmp project, verify = `true` (always pass)."""
    (tmp_path / "file.txt").write_text("v1")
    db = tmp_path / ".babysitter" / "babysitter.db"
    weak = ScriptedProvider("weak", [ModelTurn("hi", [])])
    strong = ScriptedProvider("strong", [ModelTurn("hi-strong", [])])
    config = ServerConfig(
        project_root=str(tmp_path),
        db_path=str(db),
        providers={"weak": weak, "strong": strong},
        ladder=["weak", "strong"],
        verify={"test": ["true"]},
    )
    client = TestClient(create_app(config))
    store = BabysitterStore(db)
    yield client, store, tmp_path, weak, strong
    store.close()


def task_ids(store):
    return [t.id for t in store.list_tasks()]


def test_healthz_and_models(harness):
    client, *_ = harness
    assert client.get("/healthz").json()["status"] == "ok"
    models = client.get("/v1/models").json()["data"]
    assert [m["id"] for m in models] == ["weak", "strong"]


def test_chat_completion_repairs_before_agent_sees_it(harness):
    client, store, _, weak, _ = harness
    weak.script[:] = [ModelTurn("writing", [ToolCall(
        "c1", "write_note", '{path: "n.txt", content: "hi",}')])]
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "weak", "messages": [{"role": "user", "content": "go"}],
              "tools": [AGENT_TOOL]},
        headers={"x-babysitter-session": "s1"},
    )
    assert resp.status_code == 200
    msg = resp.json()["choices"][0]["message"]
    call = msg["tool_calls"][0]
    # The agent receives VALID JSON even though the model emitted garbage.
    assert json.loads(call["function"]["arguments"]) == {
        "path": "n.txt", "content": "hi"}
    task_id = task_ids(store)[0]
    assert store.count_events(task_id, KIND_VALIDATION_FAILED) == 1
    assert store.count_events(task_id, KIND_REPAIR_APPLIED) == 1


def test_session_continuity_one_task(harness):
    client, store, *_ = harness
    for _ in range(2):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "weak",
                  "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-babysitter-session": "same"},
        )
        assert resp.status_code == 200
    assert len(task_ids(store)) == 1


def test_changed_tree_between_turns_gets_verified(harness, tmp_path):
    client, store, proj, weak, _ = harness
    weak.script[:] = [ModelTurn("ok", []), ModelTurn("ok2", [])]
    headers = {"x-babysitter-session": "s"}
    body = {"model": "weak", "messages": [{"role": "user", "content": "hi"}]}
    assert client.post("/v1/chat/completions", json=body, headers=headers).status_code == 200
    # The agent changed a file behind our back; next turn must verify it.
    (proj / "file.txt").write_text("v2")
    assert client.post("/v1/chat/completions", json=body, headers=headers).status_code == 200
    task_id = task_ids(store)[0]
    started = store.list_events(task_id, kinds=["verification.started"])
    assert len(started) == 1
    assert started[0].payload["trigger"] == "post-change"


def test_failed_verification_injected(harness, tmp_path):
    """Dedicated app whose verify command fails: the forwarded messages
    for the next turn must carry the failure context."""
    (tmp_path / "fail.sh").write_text("#!/bin/sh\necho KABOOM >&2\nexit 1\n")
    db = tmp_path / ".babysitter" / "db2.sqlite"
    weak = ScriptedProvider("weak", [ModelTurn("ok", []), ModelTurn("ok2", [])])
    app = create_app(ServerConfig(
        project_root=str(tmp_path), db_path=str(db),
        providers={"weak": weak}, ladder=["weak"],
        verify={"test": ["sh", "fail.sh"]}))
    client = TestClient(app)
    headers = {"x-babysitter-session": "s"}
    body = {"model": "weak", "messages": [{"role": "user", "content": "hi"}]}
    assert client.post("/v1/chat/completions", json=body, headers=headers).status_code == 200
    (tmp_path / "file.txt").write_text("v2-broken")
    assert client.post("/v1/chat/completions", json=body, headers=headers).status_code == 200
    forwarded = weak.calls[1]["messages"]
    assert any("KABOOM" in str(m.get("content", "")) for m in forwarded)
    store = BabysitterStore(db)
    task_id = [t.id for t in store.list_tasks()][0]
    assert store.count_events(task_id, KIND_VERIFICATION_FAILED) == 1
    store.close()


def test_consecutive_tool_errors_escalate(harness):
    client, store, _, weak, strong = harness
    weak.script[:] = [ModelTurn("try", []), ModelTurn("try-again", [])]
    strong.script[:] = [ModelTurn("strong-takeover", [])]
    headers = {"x-babysitter-session": "esc"}
    err_body = {"model": "weak", "messages": [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "write_note", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1",
         "content": "Error: something exploded"},
    ]}
    client.post("/v1/chat/completions", json=err_body, headers=headers)
    resp = client.post("/v1/chat/completions", json=err_body, headers=headers)
    assert resp.status_code == 200
    task_id = task_ids(store)[0]
    triggered = store.list_events(task_id, kinds=[KIND_ESCALATION_TRIGGERED])
    assert len(triggered) == 1
    assert triggered[0].payload["to_model"] == "strong"
    # The THIRD turn must be served by the strong model.
    client.post("/v1/chat/completions",
                json={"model": "weak",
                      "messages": [{"role": "user", "content": "hi"}]},
                headers=headers)
    assert len(strong.calls) == 1


def test_stream_rejected(harness):
    client, *_ = harness
    resp = client.post("/v1/chat/completions",
                       json={"model": "weak", "messages": [], "stream": True})
    assert resp.status_code == 400


def test_provider_failure_is_502(harness):
    from babysitter.provider import ProviderError

    client, _, _, weak, _ = harness

    def boom(messages, tools, index):
        raise ProviderError("down")

    weak.script[:] = [boom]
    resp = client.post("/v1/chat/completions",
                       json={"model": "weak",
                             "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 502


# -- Anthropic adapter ----------------------------------------------------------


def test_messages_roundtrip_with_tool_use(harness):
    client, store, _, weak, _ = harness
    weak.script[:] = [ModelTurn("writing", [ToolCall(
        "toolu-1", "write_note", '{"path": "n", "content": "c"}')])]
    resp = client.post("/v1/messages", json={
        "model": "claude-x", "max_tokens": 100,
        "system": "be terse",
        "messages": [{"role": "user", "content": "go"}],
        "tools": [{"name": "write_note", "description": "w",
                   "input_schema": {"type": "object", "required": ["path"],
                                    "properties": {"path": {"type": "string"},
                                                   "content": {"type": "string"}}}}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stop_reason"] == "tool_use"
    use = [b for b in data["content"] if b["type"] == "tool_use"][0]
    assert use["name"] == "write_note" and use["input"]["path"] == "n"
    # Babysitter serves its tier model, not the requested id (documented).
    assert data["model"] == "weak"


def test_messages_tool_result_blocks_translate(harness):
    client, _, _, weak, _ = harness
    weak.script[:] = [ModelTurn("done", [])]
    resp = client.post("/v1/messages", json={
        "model": "claude-x", "max_tokens": 100,
        "messages": [
            {"role": "assistant",
             "content": [{"type": "tool_use", "id": "t1", "name": "write_note",
                          "input": {"path": "n"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "Error: disk full", "is_error": True}]},
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["stop_reason"] == "end_turn"
    forwarded = weak.calls[0]["messages"]
    tool_msgs = [m for m in forwarded if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and "disk full" in tool_msgs[0]["content"]


def test_messages_rejects_unsupported_blocks(harness):
    client, *_ = harness
    resp = client.post("/v1/messages", json={
        "model": "claude-x", "max_tokens": 100,
        "messages": [{"role": "user",
                      "content": [{"type": "image",
                                   "source": {"type": "base64"}}]}],
    })
    assert resp.status_code == 400

import json
from contextlib import asynccontextmanager

import httpx
import pytest

from babysitter.protocol import normalize
from babysitter.provider import OpenAIProvider, ProviderError
from babysitter.runtime import SupervisionError
from babysitter.server import create_app
from babysitter.tools import TOOLS
from conftest import ScriptedProvider, answer, call, tool_response


@asynccontextmanager
async def client_for(workspace, config, responses):
    provider = ScriptedProvider(responses)
    app = create_app(workspace, config, provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            yield client, app, provider


async def test_openai_managed_roundtrip(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    async with client_for(workspace, config, [tool_response(call()), answer()]) as (client, app, provider):
        response = await client.post("/v1/chat/completions", json={"model": "babysitter", "messages": [{"role": "user", "content": "Fix"}]},
                                     headers={"X-Babysitter-Execute": "true"})
        assert response.status_code == 200, response.text
        assert response.headers["X-Babysitter-State"] == "verified_complete"
        assert response.headers["X-Babysitter-Verified"] == "true"
        assert response.json()["choices"][0]["message"]["content"] == "Done"
        assert (await client.get("/v1/models")).json()["data"][0]["id"] == "weak"


@pytest.mark.parametrize("protocol,path", [("openai", "/v1/chat/completions"), ("anthropic", "/v1/messages")])
async def test_buffered_streaming(protocol, path, workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    async with client_for(workspace, config, [answer("Verified")]) as (client, _, _):
        body = {"model": "babysitter", "max_tokens": 100, "messages": [{"role": "user", "content": "Check"}], "stream": True}
        response = await client.post(path, json=body)
        assert response.status_code == 200, response.text
        assert response.headers["X-Babysitter-Verified"] == "true"
        assert response.headers["X-Babysitter-Stream"] == "buffered-until-validated"
        assert "Verified" in response.text
        assert ("[DONE]" if protocol == "openai" else "event: message_stop") in response.text


async def test_relay_is_awaiting_not_complete_and_resumes(workspace, setup_runtime):
    config, _, project, _ = setup_runtime
    async with client_for(workspace, config, [tool_response(call(raw="{path: 'calc.py', content: '# caller edit\\n',}")), answer()]) as (client, app, _):
        messages = [{"role": "user", "content": "Add a comment"}]
        response = await client.post("/v1/chat/completions", json={"model": "weak", "messages": messages, "tools": TOOLS})
        assert response.status_code == 200, response.text
        task_id = response.headers["X-Babysitter-Task"]
        assert response.headers["X-Babysitter-State"] == "awaiting_tools"
        assert response.headers["X-Babysitter-Verified"] == "false"
        assert "def add" in (workspace / "calc.py").read_text()  # relay did NOT execute
        assistant = response.json()["choices"][0]["message"]
        assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "calc.py", "content": "# caller edit\n"}
        (workspace / "calc.py").write_text((workspace / "calc.py").read_text() + "# caller actually changed it\n")
        messages.extend([assistant, {"role": "tool", "tool_call_id": "call-1", "content": '{"ok":true}'}])
        response = await client.post("/v1/chat/completions", json={"model": "weak", "messages": messages, "tools": TOOLS}, headers={"X-Babysitter-Task": task_id})
        assert response.status_code == 200, response.text
        assert response.headers["X-Babysitter-State"] == "verified_complete"
        assert any(e["kind"] == "client.tool_result" for e in app.state.runtime.store.trace(task_id)["events"])


async def test_new_task_blocked_while_relay_owns_workspace(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    async with client_for(workspace, config, [tool_response(call())]) as (client, _, _):
        body = {"model": "weak", "messages": [{"role": "user", "content": "Fix"}], "tools": TOOLS}
        response = await client.post("/v1/chat/completions", json=body)
        assert response.status_code == 200
        assert (await client.post("/v1/chat/completions", json=body)).status_code == 409
        task_id = response.headers["X-Babysitter-Task"]
        assert (await client.post("/v1/chat/completions", json=body, headers={"X-Babysitter-Task": task_id})).status_code == 409


async def test_anthropic_tool_use_roundtrip(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    tools = [{"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]} for t in TOOLS]
    async with client_for(workspace, config, [tool_response(call("read_file", args={"path": "calc.py"})), answer()]) as (client, _, provider):
        messages = [{"role": "user", "content": "Read the file"}]
        body = {"model": "babysitter", "max_tokens": 500, "system": [{"type": "text", "text": "Be precise"}], "messages": messages, "tools": tools}
        response = await client.post("/v1/messages", json=body)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["stop_reason"] == "tool_use" and data["content"][0]["input"] == {"path": "calc.py"}
        messages.extend([{"role": "assistant", "content": data["content"]}, {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call-1", "content": [{"type": "text", "text": "file contents"}]}]}])
        response = await client.post("/v1/messages", json=body, headers={"X-Babysitter-Task": response.headers["X-Babysitter-Task"]})
        assert response.status_code == 200, response.text
        assert response.json()["stop_reason"] == "end_turn"
        assert provider.requests[0]["messages"][0] == {"role": "system", "content": "Be precise"}


async def test_unavailable_response_is_not_success(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    config.test_command = []
    async with client_for(workspace, config, [answer("Success!")]) as (client, _, _):
        response = await client.post("/v1/chat/completions", json={"model": "weak", "messages": [{"role": "user", "content": "Check"}]})
        assert response.status_code == 409
        assert response.headers["X-Babysitter-State"] == "verification_unavailable"
        assert "NOT verified" in response.text


async def test_local_auth_and_browser_boundary(workspace, setup_runtime, monkeypatch):
    config, _, _, _ = setup_runtime
    monkeypatch.setenv(config.token_env, "local-token")
    async with client_for(workspace, config, [answer()]) as (client, _, _):
        assert (await client.get("/v1/models")).status_code == 401
        assert (await client.get("/v1/models", headers={"Authorization": "Bearer local-token"})).status_code == 200
        assert (await client.get("/v1/models", headers={"x-api-key": "local-token"})).status_code == 200
        assert (await client.get("/v1/models", headers={"x-api-key": "local-token", "origin": "https://evil.example"})).status_code == 403


async def test_non_loopback_requires_token(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    async with client_for(workspace, config, [answer()]) as (client, _, _):
        assert (await client.get("/v1/models", headers={"host": "evil.example"})).status_code == 403


@pytest.mark.parametrize("body", [[], {}, {"model": "weak", "messages": []},
    {"model": "weak", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {}}]}]},
    {"model": "weak", "messages": [{"role": "user", "content": "Hi"}], "n": 2}])
async def test_bad_requests_fail_cleanly(body, workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    async with client_for(workspace, config, [answer()]) as (client, _, _):
        response = await client.post("/v1/chat/completions", json=body)
        assert response.status_code == 422, response.text


async def test_http_provider_adapter(setup_runtime):
    config, _, _, _ = setup_runtime
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": [{"id": "weak"}]})
        return httpx.Response(200, json=answer())
    provider = OpenAIProvider(config)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url="http://provider/v1/", transport=httpx.MockTransport(handler))
    try:
        assert (await provider.models())["data"][0]["id"] == "weak"
        result = await provider.complete([{"role": "user", "content": "Hi"}], [], "weak", {})
        assert result["choices"][0]["message"]["content"] == "Done"
        assert json.loads(calls[1].content)["stream"] is False
    finally:
        await provider.close()


async def test_relay_continuation_survives_runtime_restart(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    messages = [{"role": "user", "content": "Read"}]
    async with client_for(workspace, config, [tool_response(call("read_file", args={"path": "calc.py"}))]) as (client, _, _):
        response = await client.post("/v1/chat/completions", json={"model": "weak", "messages": messages, "tools": TOOLS})
        assert response.status_code == 200
        task_id = response.headers["X-Babysitter-Task"]
        messages.extend([response.json()["choices"][0]["message"], {"role": "tool", "tool_call_id": "call-1", "content": "contents"}])
    async with client_for(workspace, config, [answer()]) as (client, _, _):
        response = await client.post("/v1/chat/completions", json={"model": "weak", "messages": messages, "tools": TOOLS}, headers={"X-Babysitter-Task": task_id})
        assert response.status_code == 200, response.text
        assert response.headers["X-Babysitter-Verified"] == "true"


async def test_interrupted_turn_is_failed_not_verified_on_restart(workspace, setup_runtime):
    config, store, _, _ = setup_runtime
    task = store.create("interrupted", "weak")
    store.event(task["id"], "execute", "tools.started", {}, state="executing")
    async with client_for(workspace, config, [answer()]) as (client, app, _):
        assert app.state.runtime.store.task(task["id"])["state"] == "failed"
        response = await client.post("/v1/chat/completions", json={"model": "weak", "messages": [{"role": "user", "content": "New task"}]})
        assert response.status_code == 200


async def test_relay_tool_failure_context_reaches_retry(workspace, setup_runtime):
    config, _, _, _ = setup_runtime
    async with client_for(workspace, config, [tool_response(call()), answer()]) as (client, app, provider):
        messages = [{"role": "user", "content": "Change"}]
        response = await client.post("/v1/chat/completions", json={"model": "weak", "messages": messages, "tools": TOOLS})
        task_id = response.headers["X-Babysitter-Task"]
        messages.extend([response.json()["choices"][0]["message"], {"role": "tool", "tool_call_id": "call-1", "content": '{"error":"permission denied"}'}])
        response = await client.post("/v1/chat/completions", json={"model": "weak", "messages": messages, "tools": TOOLS}, headers={"X-Babysitter-Task": task_id})
        assert response.status_code == 200
        assert "permission denied" in json.dumps(provider.requests[-1]["messages"])
        assert any(e["kind"] == "rollback.completed" for e in app.state.runtime.store.trace(task_id)["events"])

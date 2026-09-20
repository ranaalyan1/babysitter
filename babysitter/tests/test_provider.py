"""Provider tests: the real OpenAI-compatible client against a real
(local stub) HTTP endpoint, plus the scripted double."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from babysitter.provider import (
    ModelTurn,
    OpenAICompatProvider,
    ProviderError,
    ScriptedProvider,
    ToolCall,
)


class StubHandler(BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, *args):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models" and StubHandler.mode == "ok":
            self._send(200, {"object": "list", "data": [{"id": "stub"}]})
        else:
            self._send(500, {"error": "down"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if StubHandler.mode == "http500":
            self._send(500, {"error": "kaput"})
            return
        if StubHandler.mode == "badjson":
            raw = b"not json{{{"
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        assert body["model"] == "stub-model"
        self._send(200, {
            "choices": [{
                "message": {
                    "content": "here you go",
                    "tool_calls": [{
                        "id": "call-9",
                        "type": "function",
                        "function": {"name": "read_file",
                                     "arguments": '{"path": "a"}'},
                    }],
                }
            }]
        })


@pytest.fixture()
def stub_url():
    server = HTTPServer(("127.0.0.1", 0), StubHandler)
    StubHandler.mode = "ok"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def test_openai_compat_parses_tool_calls(stub_url):
    provider = OpenAICompatProvider("stub-model", stub_url)
    turn = provider.complete([{"role": "user", "content": "hi"}], tools=[])
    assert turn.content == "here you go"
    assert len(turn.tool_calls) == 1
    call = turn.tool_calls[0]
    assert (call.call_id, call.name) == ("call-9", "read_file")
    assert json.loads(call.args_raw) == {"path": "a"}


def test_openai_compat_http_error_is_provider_error(stub_url):
    StubHandler.mode = "http500"
    provider = OpenAICompatProvider("stub-model", stub_url)
    with pytest.raises(ProviderError):
        provider.complete([], [])


def test_openai_compat_bad_json_is_provider_error(stub_url):
    StubHandler.mode = "badjson"
    provider = OpenAICompatProvider("stub-model", stub_url)
    with pytest.raises(ProviderError):
        provider.complete([], [])


def test_check_reports_ok_and_unreachable(stub_url):
    assert OpenAICompatProvider("m", stub_url).check() == "ok"
    assert "unreachable" in OpenAICompatProvider(
        "m", "http://127.0.0.1:1/v1").check()


def test_scripted_provider_plays_script_and_records():
    script = [
        ModelTurn(content="first", tool_calls=[
            ToolCall("c1", "read_file", '{"path": "a"}')]),
        ModelTurn(content="done", tool_calls=[]),
    ]
    provider = ScriptedProvider("weak", script)
    t1 = provider.complete([{"role": "user", "content": "go"}], [])
    t2 = provider.complete([], [])
    t3 = provider.complete([], [])  # script exhausted: repeats last turn
    assert (t1.content, t2.content, t3.content) == ("first", "done", "done")
    assert len(provider.calls) == 3
    assert provider.calls[0]["messages"] == [{"role": "user", "content": "go"}]


def test_scripted_provider_rejects_empty_script():
    with pytest.raises(ValueError):
        ScriptedProvider("weak", [])

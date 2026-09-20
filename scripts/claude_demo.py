#!/usr/bin/env python3
"""Exercise REAL Claude Code hooks against a local scripted Messages fixture.

No API subscription or real LLM is used. This tests the installed agent, actual
native Read/Write tools, hook registration, Stop feedback, rollback and checks.
Use only the disposable repository that this script creates.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aletheia.adapters.claude_install import install
from aletheia.config import Config
from aletheia.metrics import metrics
from aletheia.protocol import anthropic_response, stream_events
from aletheia.state import Store, uid
from demo import create_fixture


def run(claude: str, output: Path | None = None) -> dict:
    root = Path.cwd() / ".aletheia" / ("claude-demo-" + uid()[:8])
    create_fixture(root)
    Config(test_command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
           typecheck_command=[sys.executable, "-m", "mypy"]).save(root)
    install(root)
    bad = "def add(a: int, b: int) -> int:\n    return a - b\n"
    good = "def add(a: int, b: int) -> int:\n    # Corrected after independent verification.\n    return a + b\n"
    calls = []
    marker = "native-aletheia-e2e"
    filename = str(root / "calc.py")

    class MessagesFixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.split("?")[0].endswith("/count_tokens"):
                encoded = json.dumps({"input_tokens": 500}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            main_request = marker in json.dumps(body.get("messages", []))
            if main_request:
                calls.append(body)
            number = len(calls)
            message: dict = {"role": "assistant", "content": "The change is complete."}
            tool = None
            if main_request and number in {1, 4}:
                tool = ("Read", {"file_path": filename})
            elif main_request and number in {2, 5}:
                tool = ("Write", {"file_path": filename, "content": bad if number == 2 else good})
            if tool:
                message = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": f"toolu_fixture_{number}", "type": "function", "function": {"name": tool[0], "arguments": json.dumps(tool[1])}}]}
            response = {"id": f"msg_fixture_{uid()}", "model": body.get("model", "fixture"),
                        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool else "stop"}],
                        "usage": {"prompt_tokens": 500, "completion_tokens": 50}}
            encoded = ("".join(stream_events(response, "anthropic")) if body.get("stream") else json.dumps(anthropic_response(response))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if body.get("stream") else "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), MessagesFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    home = root / ".aletheia" / "claude-home"
    home.mkdir()
    # Never inherit real provider credentials, cloud-provider switches or user
    # Claude configuration. The fixture key is deliberately not a real credential.
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "TMPDIR"}}
    env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home),
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}", "ANTHROPIC_API_KEY": "aletheia-fixture-not-a-real-key",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
                "NO_PROXY": "127.0.0.1,localhost"})
    started = time.monotonic()
    try:
        version = subprocess.check_output([claude, "--version"], env=env, text=True, timeout=15).strip()
        command = [claude, "-p", f"{marker}: Update calc.py; recover from verification failures before finishing.",
                   "--model", "claude-haiku-4-5", "--tools", "Read,Write", "--allowedTools", "Read", "Write",
                   "--max-turns", "10", "--output-format", "json", "--debug-file", str(root / ".aletheia" / "claude-debug.log")]
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=120)
        (root / ".aletheia" / "claude-stdout.json").write_text(result.stdout)
        (root / ".aletheia" / "claude-stderr.log").write_text(result.stderr)
        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI returned {result.returncode}: {result.stderr[-2000:]} {result.stdout[-2000:]}. Logs: {root / '.aletheia'}")
        store = Store(root / ".aletheia")
        try:
            trace = store.trace()
        finally:
            store.close()
        (root / ".aletheia" / "trace.json").write_text(json.dumps(trace, indent=2))
        if len(trace["tasks"]) != 1 or trace["tasks"][0]["state"] != "verified_complete":
            raise RuntimeError(f"Claude ended but Aletheia did NOT verify the task. Inspect {root / '.aletheia'}")
        evidence = [e["payload"] for e in trace["events"] if e["kind"] == "verification.result"]
        assert [e["status"] for e in evidence] == ["failed", "passed"]
        assert (root / "calc.py").read_text() == good
        assert len(calls) == 6, len(calls)
        assert "rolled back" in json.dumps(calls[3]["messages"])
        report = {"agent": version, "native_cli_executed": True, "real_model_tested": False, "scripted_provider_fixture": True,
                  "task_id": trace["tasks"][0]["id"], "state": "verified_complete", "human_interventions": 0,
                  "elapsed_seconds": round(time.monotonic() - started, 3), "native_model_requests": len(calls),
                  "tool_results_observed": len([e for e in trace["events"] if e["kind"] == "tool.result"]),
                  "verification": [{"status": e["status"], "commands": [{"name": c["name"], "exit_code": c["exit_code"],
                                   "output_tail": (c["stdout"] + c["stderr"])[-1500:]} for c in e["commands"]]} for e in evidence],
                  "metrics": metrics(trace), "trace": str(root / ".aletheia" / "trace.json")}
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", default=shutil.which("claude"), help="path to an officially installed Claude Code executable")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.claude:
        parser.error("Claude Code is not on PATH. Install it officially or supply --claude /path/to/claude")
    print(json.dumps(run(args.claude, args.output), indent=2))

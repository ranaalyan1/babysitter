#!/usr/bin/env python3
"""Reproducible end-to-end fault injection, NOT a real-model quality benchmark.

The upstream fixture speaks actual HTTP OpenAI Chat Completions. The Babysitter
FastAPI application is exercised through ASGI, or the real CLI server over TCP
with --http. File tools, git checkpoints, pytest, mypy, SQLite, rollback and retries
are all real.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from babysitter.config import Config
from babysitter.metrics import metrics
from babysitter.server import create_app
from babysitter.state import Store, uid


@asynccontextmanager
async def runtime_client(root: Path, config: Config, over_http: bool):
    """Exercise either the ASGI app or the installed CLI in a separate process."""
    if not over_http:
        app = create_app(root, config)
        token = os.environ.get(config.token_env)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", timeout=300,
                                         headers={"Authorization": f"Bearer {token}"} if token else {}, trust_env=False) as client:
                yield client, app.state.runtime.store
        return

    # Persist only ordinary config; ephemeral local auth stays in the environment.
    config.save(root)
    token = secrets.token_urlsafe(32)
    env = {**os.environ, config.token_env: token, "PYTHONUNBUFFERED": "1"}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "babysitter.cli", "--root", str(root), "start", "--host", "0.0.0.0", "--port", "0",
        env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output = bytearray()
    drain = None
    try:
        assert process.stdout is not None
        async with asyncio.timeout(20):
            while line := await process.stdout.readline():
                output.extend(line)
                match = re.search(rb"Uvicorn running on http://0\.0\.0\.0:(\d+)", line)
                if match:
                    port = int(match[1])
                    break
            else:
                raise RuntimeError("CLI server failed to start:\n" + output.decode(errors="replace"))
        drain = asyncio.create_task(process.communicate())
        store = Store(root / ".babysitter")
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=300, trust_env=False,
                                         headers={"Authorization": f"Bearer {token}"}) as client:
                models = await client.get("/v1/models")
                models.raise_for_status()
                assert any(model["id"] == config.model for model in models.json()["data"])
                yield client, store
        finally:
            store.close()
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        if drain:
            remainder, _ = await drain
            output.extend(remainder)
        log = root / ".babysitter" / "demo-server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(output)


async def run_demo(root: Path, filename: str, bad: str, good: str, *, fail_twice: bool = False,
                   over_http: bool = False) -> dict:
    requests = []
    failures_required = 2 if fail_twice else 1

    class WeakModelFixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_json({"object": "list", "data": [{"id": "fixture-weak", "object": "model"}, {"id": "fixture-strong", "object": "model"}]})

        def send_json(self, body, status=200):
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            number = len(requests)
            result = {"id": "chatcmpl-fixture-" + str(number), "object": "chat.completion", "created": int(time.time()),
                      "model": body["model"], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
            if number <= failures_required + 1:
                if number > 1 and not any("Babysitter detected" in str(m.get("content")) and "rolled back" in str(m.get("content")) for m in body["messages"]):
                    self.send_json({"error": "Fixture requires actual failure and rollback feedback"}, 500)
                    return
                content = (bad + ("\n" if number > 1 else "")) if number <= failures_required else good
                args = json.dumps({"path": filename, "content": content})
                if number == 1:
                    args = args[:-1] + ",}"  # weak model produces a malformed trailing comma
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": f"call-{number}", "type": "function",
                           "function": {"name": "write_file", "arguments": args}}]}
                result["choices"] = [{"index": 0, "message": message, "finish_reason": "tool_calls"}]
            else:
                if not any("verification PASSED" in str(m.get("content")) for m in body["messages"]):
                    self.send_json({"error": "Fixture did not receive passing evidence"}, 500)
                    return
                result["choices"] = [{"index": 0, "message": {"role": "assistant", "content": "Corrected the change; configured tests and typecheck passed."}, "finish_reason": "stop"}]
            self.send_json(result)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), WeakModelFixture)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    config = Config(provider_url=f"http://127.0.0.1:{upstream.server_port}/v1", model="fixture-weak", stronger_model="fixture-strong",
                    test_command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    typecheck_command=[sys.executable, "-m", "mypy"], allow_managed_tools=True, max_attempts=6,
                    command_timeout=120, max_snapshot_bytes=50_000_000)
    started = time.monotonic()
    try:
        async with runtime_client(root, config, over_http) as (client, store):
            response = await client.post("/v1/chat/completions", json={"model": "babysitter", "messages": [
                {"role": "user", "content": f"Apply the proposed change to {filename}. Recover from failed checks and finish only with passing evidence."}]},
                headers={"X-Babysitter-Execute": "true"})
            if response.status_code != 200:
                raise RuntimeError(f"Demo failed: {response.status_code} {response.text}")
            task_id = response.headers["X-Babysitter-Task"]
            trace = store.trace(task_id)
            (root / ".babysitter" / f"demo-{task_id}.json").write_text(json.dumps(trace, indent=2))
            verifications = [event["payload"] for event in trace["events"] if event["kind"] == "verification.result"]
            assert [v["status"] for v in verifications] == ["failed"] * failures_required + ["passed", "passed"]
            assert (root / filename).read_text() == good
            assert response.headers["X-Babysitter-State"] == "verified_complete"
            model_sequence = [request["model"] for request in requests]
            assert model_sequence == (["fixture-weak", "fixture-weak", "fixture-strong", "fixture-weak"] if fail_twice else ["fixture-weak"] * 3)
            report = {"fixture_provider": True, "real_model_quality_evaluated": False, "human_interventions": 0,
                      "transport": "CLI server over TCP + real HTTP upstream" if over_http else "in-process ASGI runtime + real HTTP upstream", "project": root.name,
                      "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                      "task_id": task_id, "state": response.headers["X-Babysitter-State"], "model_sequence": model_sequence,
                      "elapsed_seconds": round(time.monotonic() - started, 3), "metrics": metrics(trace),
                      "verification": [{"status": v["status"], "files": v["files"], "fingerprint": v["fingerprint"],
                         "commands": [{"name": c["name"], "argv": c["argv"], "exit_code": c["exit_code"],
                                       "output_tail": (c["stdout"] + c["stderr"])[-1500:]} for c in v["commands"]]} for v in verifications],
                      "checkpoint_count": len(trace["checkpoints"]), "trace_file": str(root / ".babysitter" / f"demo-{task_id}.json")}
            return report
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


def create_fixture(root: Path):
    root.mkdir(parents=True)
    (root / ".gitignore").write_text(".babysitter/\n__pycache__/\n.pytest_cache/\n.mypy_cache/\n")
    (root / "calc.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    (root / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    (root / "pyproject.toml").write_text('[tool.mypy]\nfiles = ["calc.py"]\nstrict = true\n')
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Babysitter Demo", "-c", "user.email=demo@localhost", "commit", "-qm", "demo baseline"], cwd=root, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--http", action="store_true", help="start the real CLI server and exercise both sides over TCP")
    parser.add_argument("--fail-twice", action="store_true", help="exercise step-only stronger-model escalation")
    args = parser.parse_args()
    root = Path.cwd() / ".babysitter" / ("demo-" + uid()[:8])
    create_fixture(root)
    report = asyncio.run(run_demo(root, "calc.py", "def add(a: int, b: int) -> int:\n    return a - b\n",
                                 "def add(a: int, b: int) -> int:\n    # Return the sum, not the difference.\n    return a + b\n", fail_twice=args.fail_twice, over_http=args.http))
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

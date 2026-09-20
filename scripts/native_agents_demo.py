#!/usr/bin/env python3
"""Official Codex/OpenCode binaries, actual native tools, local scripted models.

Only disposable git fixtures and isolated native homes are used. No credentials
are inherited; no real LLM or real-model effectiveness claim. Codex hook trust
bypass is EXPLICITLY test-only for this generated, inspected hook configuration.
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

from aletheia.adapters.codex_install import install
from aletheia.config import Config
from aletheia.metrics import metrics
from aletheia.state import Store, uid
from demo import create_fixture

BAD = "def add(a: int, b: int) -> int:\n    return a - b\n"
GOOD = "def add(a: int, b: int) -> int:\n    # Corrected after independent verification.\n    return a + b\n"


def responses_events(number: int, item: dict) -> str:
    response = {"id": f"resp_fixture_{number}", "object": "response", "created_at": int(time.time()),
                "model": "fixture", "status": "in_progress", "output": []}
    events = [("response.created", {"response": response})]
    partial = {**item, "status": "in_progress"}
    if item["type"] == "message":
        partial["content"] = []
    else:
        partial["input"] = ""
    events.append(("response.output_item.added", {"output_index": 0, "item": partial}))
    if item["type"] == "message":
        text = item["content"][0]["text"]
        common = {"item_id": item["id"], "output_index": 0, "content_index": 0}
        events += [("response.content_part.added", {**common, "part": {"type": "output_text", "text": "", "annotations": []}}),
                   ("response.output_text.delta", {**common, "delta": text}),
                   ("response.output_text.done", {**common, "text": text}),
                   ("response.content_part.done", {**common, "part": item["content"][0]})]
    else:
        events.append(("response.custom_tool_call_input.delta", {"item_id": item["id"], "output_index": 0, "delta": item["input"]}))
        events.append(("response.custom_tool_call_input.done", {"item_id": item["id"], "output_index": 0, "input": item["input"]}))
    events += [("response.output_item.done", {"output_index": 0, "item": item}),
               ("response.completed", {"response": {**response, "status": "completed", "output": [item],
                         "usage": {"input_tokens": 500, "output_tokens": 50, "total_tokens": 550}}})]
    return ''.join(f'event: {kind}\ndata: {json.dumps({"type": kind, "sequence_number": seq, **data})}\n\n' for seq, (kind, data) in enumerate(events))


def run(agent: str, executable: str, output: Path | None = None, project_path: Path | None = None) -> dict:
    filename, bad, good = "calc.py", BAD, GOOD
    old_line, broken_line, fixed_lines = "    return a + b", "    return a - b", "    # Corrected after independent verification.\n    return a + b"
    if project_path:
        root = project_path.resolve()
        cases = {
            "itsdangerous": ("src/itsdangerous/encoding.py", 'return base64.urlsafe_b64encode(string).rstrip(b"=")', 'return base64.urlsafe_b64encode(string)', "# URL-safe tokens omit base64 padding.", "672971d66a2ef9f85151e53283113f33d642dabd"),
            "click": ("src/click/utils.py", 'return " ".join(words)  # no truncation needed', 'return "BROKEN " + " ".join(words)  # injected faulty change', "# Preserve unchanged help when no truncation is needed.", "6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1"),
        }
        if root.name not in cases:
            raise ValueError("Only explicit disposable itsdangerous/click validation clones are supported")
        filename, original, broken, comment, revision = cases[root.name]
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=root).strip():
            raise ValueError("Fault injection requires a clean disposable clone; no reset is performed")
        if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != revision:
            raise ValueError("Use the documented pinned validation revision")
        content = (root / filename).read_text()
        if content.count(original) != 1:
            raise ValueError("Expected a unique source marker")
        old_line = next(line for line in content.splitlines() if original in line)
        indent = old_line[:len(old_line) - len(old_line.lstrip())]
        broken_line = old_line.replace(original, broken)
        fixed_lines = indent + comment + "\n" + old_line
        bad, good = content.replace(old_line, broken_line), content.replace(old_line, fixed_lines)
        ignore = root / ".gitignore"
        ignore.write_text(ignore.read_text().rstrip() + "\n.aletheia/\n")
    else:
        root = Path.cwd() / ".aletheia" / (agent + "-demo-" + uid()[:8])
        create_fixture(root)
    Config(test_command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
           typecheck_command=[sys.executable, "-m", "mypy", "--no-incremental"] + ([] if project_path else ["calc.py"])).save(root)
    home = root / ".aletheia" / "native-home"
    home.mkdir(parents=True)
    calls: list[dict] = []
    marker = "native-aletheia-e2e"

    class ModelFixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            main_request = marker in json.dumps(body.get("messages", body.get("input", [])))
            if main_request:
                calls.append(body)
                (root / ".aletheia" / "model-requests.json").write_text(json.dumps(calls, indent=2))
            number = len(calls)
            if agent == "codex":
                if main_request and number in {1, 3}:
                    replacement = broken_line if number == 1 else fixed_lines
                    patch = f"*** Begin Patch\n*** Update File: {root / filename}\n@@\n-{old_line}\n+" + replacement.replace("\n", "\n+") + "\n*** End Patch"
                    item = {"type": "custom_tool_call", "id": f"ctc_{number}", "call_id": f"call_{number}", "name": "apply_patch", "input": patch, "status": "completed"}
                else:
                    item = {"type": "message", "id": f"msg_{number}", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "The change is complete.", "annotations": []}]}
                encoded = responses_events(number, item).encode()
            else:
                tool = None
                if main_request and number in {1, 4}:
                    tool = ("read", {"filePath": str(root / filename)})
                elif main_request and number in {2, 5}:
                    tool = ("write", {"filePath": str(root / filename), "content": bad if number == 2 else good})
                message: dict = {"role": "assistant", "content": "The change is complete."}
                if tool:
                    message = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{number}", "type": "function",
                                "function": {"name": tool[0], "arguments": json.dumps(tool[1])}}]}
                common = {"id": f"chatcmpl_fixture_{number}", "object": "chat.completion.chunk", "created": int(time.time()), "model": "fixture"}
                chunks = [{**common, "choices": [{"index": 0, "delta": message, "finish_reason": None}]},
                          {**common, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tool else "stop"}],
                           "usage": {"prompt_tokens": 500, "completion_tokens": 50, "total_tokens": 550}}]
                encoded = (''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n').encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TMPDIR"}}
    env.update({"HOME": str(home), "NO_PROXY": "127.0.0.1,localhost", "NO_COLOR": "1"})
    if project_path:
        env["PYTHONPATH"] = str(root / "src")  # Test the edited checkout, not any installed release.
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"
    goal = f"{marker}: Update {filename}; recover from independent verification failures before finishing."
    if agent == "codex":
        install(root)
        env["CODEX_HOME"] = str(home)
        (home / "config.toml").write_text(f'''model = "gpt-5.5"
model_provider = "scripted"
[model_providers.scripted]
name = "Scripted local validation only"
base_url = {json.dumps(endpoint)}
wire_api = "responses"
requires_openai_auth = false
[projects.{json.dumps(str(root))}]
trust_level = "trusted"
''')
        command = [executable, "exec", "--json", "--sandbox", "workspace-write", "--dangerously-bypass-hook-trust", goal]
    else:
        env.update({"XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
                    "OPENCODE_DISABLE_MODELS_FETCH": "true", "OPENCODE_DISABLE_AUTOUPDATE": "true"})
        (root / "opencode.json").write_text(json.dumps({"$schema": "https://opencode.ai/config.json", "model": "scripted/fixture", "share": "disabled",
            "enabled_providers": ["scripted"], "autoupdate": False,
            "permission": {"*": "deny", "read": "allow", "write": "allow", "edit": "allow"},
            "provider": {"scripted": {"npm": "@ai-sdk/openai-compatible", "name": "Scripted local validation only",
                "options": {"baseURL": endpoint, "apiKey": "local-fixture-not-a-real-key"},
                "models": {"fixture": {"name": "fixture", "limit": {"context": 32768, "output": 4096}}}}}}, indent=2))
        command = [sys.executable, "-m", "aletheia.cli", "--root", str(root), "opencode", "run", goal,
                   "--executable", executable, "--timeout", "120"]
    started = time.monotonic()
    try:
        version = subprocess.check_output([executable, "--version"], env=env, text=True, timeout=30).strip()
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=300)
        (root / ".aletheia" / "native-stdout.log").write_text(result.stdout)
        (root / ".aletheia" / "native-stderr.log").write_text(result.stderr)
        store = Store(root / ".aletheia")
        try:
            trace = store.trace()
        finally:
            store.close()
        statuses = [e["payload"]["status"] for e in trace["events"] if e["kind"] == "verification.result"]
        report = {"mode": f"official-{agent}-cli+local-scripted-model", "agent_version": version, "real_model_tested": False,
                  "project": root.name if project_path else "addition-fixture",
                  "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                  "verification": [{"status": e["payload"]["status"], "fingerprint": e["payload"].get("fingerprint"),
                      "commands": [{"name": c["name"], "argv": c["argv"], "exit_code": c["exit_code"], "output_tail": (c["stdout"] + c["stderr"])[-1500:]} for c in e["payload"].get("commands", [])]}
                      for e in trace["events"] if e["kind"] == "verification.result"],
                  "exit_code": result.returncode, "root": str(root), "model_requests": len(calls), "verification_statuses": statuses,
                  "observed_tool_results": sum(e["kind"] == "tool.result" for e in trace["events"]), "metrics": metrics(trace),
                  "test_only_hook_trust_bypass": agent == "codex", "permissions_auto_approved_by_adapter": False,
                  "duration_seconds": round(time.monotonic() - started, 3)}
        if result.returncode or statuses != ["failed", "passed"] or report["metrics"]["tasks_verified_complete"] != 1 or (root / filename).read_text() != good:
            raise RuntimeError(f"Native validation failed: {json.dumps(report)}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}\nInspect {root / '.aletheia'}")
        if len(trace["tasks"]) != 1 or not any(e["kind"] == "rollback.completed" for e in trace["events"]):
            raise RuntimeError("Expected one task and an inspectable rollback")
        if output:
            output.write_text(json.dumps(report, indent=2) + '\n')
        return report
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", choices=["codex", "opencode"])
    parser.add_argument("--executable")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--project-path", type=Path, help="INJECTS FAULTS: clean disposable pinned itsdangerous/click clone only; never use a working repository")
    args = parser.parse_args()
    executable = args.executable or shutil.which(args.agent)
    if not executable:
        parser.error("Install the official agent or pass --executable PATH")
    print(json.dumps(run(args.agent, str(Path(executable).absolute()), args.output, args.project_path), indent=2))


if __name__ == "__main__":
    main()

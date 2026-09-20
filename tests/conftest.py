from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from aletheia.config import Config
from aletheia.project import Project
from aletheia.runtime import Runtime
from aletheia.state import Store


def answer(content="Done", model="weak"):
    return {"id": "chatcmpl-test", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def call(name="write_file", args=None, raw=None, call_id="call-1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw if raw is not None else json.dumps(args or {"path": "calc.py", "content": "def add(a: int, b: int) -> int:\n    return a + b\n"})}}


def tool_response(*calls):
    result = answer(None)
    result["choices"][0]["message"]["tool_calls"] = list(calls)
    result["choices"][0]["finish_reason"] = "tool_calls"
    return result


class ScriptedProvider:
    def __init__(self, responses):
        self.responses, self.requests = responses, []

    async def complete(self, messages, tools, model, options):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": tools, "model": model, "options": options})
        response = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        result = copy.deepcopy(response)
        result["model"] = model
        return result

    async def models(self):
        return {"object": "list", "data": [{"id": "weak", "object": "model"}, {"id": "strong", "object": "model"}]}

    async def close(self):
        pass


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text(".aletheia/\n__pycache__/\n.pytest_cache/\n.mypy_cache/\n.env\n")
    (root / "calc.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    (root / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "baseline"], cwd=root, check=True)
    return root


@pytest.fixture
def setup_runtime(workspace):
    config = Config(model="weak", stronger_model="strong", allow_managed_tools=True,
                    test_command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    typecheck_command=[sys.executable, "-m", "mypy", "calc.py", "--no-incremental"],
                    max_attempts=8, command_timeout=30)
    store = Store(workspace / ".aletheia")
    project = Project(workspace, store)
    def build(responses):
        provider = ScriptedProvider(responses)
        return Runtime(project, store, config, provider), provider
    yield config, store, project, build
    store.close()

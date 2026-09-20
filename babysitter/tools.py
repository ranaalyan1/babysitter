from __future__ import annotations

import json

from .project import Project
from .repair import ToolError

TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a UTF-8 file in the supervised repository.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}}, "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "write_file", "description": "Replace a UTF-8 file. Verification runs after the whole tool batch.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "content": {"type": "string"}},
                    "required": ["path", "content"], "additionalProperties": False}}},
]


def execute(call: dict, project: Project) -> dict:
    name = call["function"]["name"]
    args = json.loads(call["function"]["arguments"])
    path = project.safe_path(args["path"], managed=True)
    if name == "read_file":
        if path.stat().st_size > 1_000_000:
            raise ToolError("read_file exceeds 1 MB limit")
        return {"path": args["path"], "content": path.read_text()}
    if name == "write_file":
        data = args["content"].encode()
        if len(data) > 1_000_000:
            raise ToolError("write_file exceeds 1 MB limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        project._durable_write(path, data)
        path.chmod(mode)
        return {"path": args["path"], "bytes_written": len(data)}
    raise ToolError(f"managed tool is not implemented: {name}")

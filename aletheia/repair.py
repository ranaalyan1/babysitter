"""Conservative schema-guided repair. Never invent required paths or content."""
from __future__ import annotations

import ast
import copy
import json
import re
import shlex
from typing import Any

from json_repair import repair_json
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .config import Config
from .project import Project, UnsafePath


class ToolError(ValueError):
    pass


def declarations(tools: list[dict]) -> dict[str, dict]:
    result = {}
    for tool in tools:
        if tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
            raise ToolError("only function tools are supported in v0.1")
        definition = tool["function"]
        name, schema = definition.get("name"), definition.get("parameters", {"type": "object"})
        if not isinstance(name, str) or not name or name in result:
            raise ToolError("tool names must be unique nonempty strings")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ToolError(f"invalid schema for {name}: {exc.message}") from exc
        # Disallow remote references: validation must not cause network requests.
        def check_refs(node):
            if isinstance(node, dict):
                for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                    if keyword in node and not str(node[keyword]).startswith("#"):
                        raise ToolError("only local JSON schema references are supported")
                for value in node.values():
                    check_refs(value)
            elif isinstance(node, list):
                for value in node:
                    check_refs(value)
        check_refs(schema)
        result[name] = schema
    return result


def parse_repair(raw: str) -> Any:
    # Handle the common defects without changing valid string payload bytes.
    # The general repair parser can trim trailing whitespace inside strings.
    pattern = r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')|([A-Za-z_]\w*)(?=\s*:)"
    quoted = re.sub(pattern, lambda match: match[1] if match[1] is not None else json.dumps(match[2]), raw)
    comma_pattern = r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')|,(?=\s*[}\]])"
    normalized = re.sub(comma_pattern, lambda match: match[1] or "", quoted)
    for parser in (json.loads, ast.literal_eval):
        try:
            value = parser(normalized)
            # literal_eval accepts tuples/sets/bytes, which are not JSON values.
            json.dumps(value, allow_nan=False)
            return value
        except (ValueError, TypeError, SyntaxError):
            pass
    return repair_json(raw, return_objects=True, skip_json_loads=True)


def coerce(value: Any, schema: dict, notes: list[str], path: str = "$") -> Any:
    kind = schema.get("type")
    if kind == "object" and isinstance(value, dict):
        value = copy.deepcopy(value)
        for key, rule in schema.get("properties", {}).items():
            if key not in value and key in schema.get("required", []):
                if "default" in rule:
                    value[key] = copy.deepcopy(rule["default"])
                elif "const" in rule:
                    value[key] = copy.deepcopy(rule["const"])
                elif len(rule.get("enum", [])) == 1:
                    value[key] = copy.deepcopy(rule["enum"][0])
                else:
                    continue
                notes.append(f"{path}.{key}: inserted schema-defined value")
            if key in value:
                value[key] = coerce(value[key], rule, notes, f"{path}.{key}")
    elif kind == "array" and isinstance(value, list) and isinstance(schema.get("items", {}), dict):
        value = [coerce(item, schema.get("items", {}), notes, f"{path}[{i}]") for i, item in enumerate(value)]
    elif isinstance(value, str):
        if kind == "integer" and re.fullmatch(r"-?(0|[1-9]\d*)", value.strip()):
            value = int(value)
            notes.append(f"{path}: string → integer")
        elif kind == "number" and re.fullmatch(r"-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?", value.strip()):
            value = float(value)
            notes.append(f"{path}: string → number")
        elif kind == "boolean" and value.lower() in {"true", "false"}:
            value = value.lower() == "true"
            notes.append(f"{path}: string → boolean")
    return value


def enforce_policy(args: dict, project: Project, config: Config, tool_name: str) -> None:
    path_keys = {"path", "file", "file_path", "filename", "directory", "cwd", "dir", "paths", "files"}
    command_keys = {"command", "cmd", "argv", "script", "shell", "code"}
    command_seen = False

    def walk(node):
        nonlocal command_seen
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in path_keys:
                    for name in value if isinstance(value, list) else [value]:
                        if not isinstance(name, str):
                            raise ToolError(f"{key} must contain path strings")
                        try:
                            project.safe_path(name, managed=True)
                        except UnsafePath as exc:
                            raise ToolError(str(exc)) from exc
                elif key.lower() in command_keys:
                    command_seen = True
                    try:
                        argv = shlex.split(value) if isinstance(value, str) else value
                    except ValueError as exc:
                        raise ToolError("malformed command") from exc
                    if not argv or argv not in [config.test_command, config.typecheck_command]:
                        raise ToolError("command not on the operator-configured verification allowlist")
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(args)
    if re.search(r"bash|shell|terminal|exec|run_command", tool_name, re.I) and not command_seen:
        raise ToolError("command tool has no recognized allowlisted command field")


def clean_call(call: dict, schemas: dict, project: Project, config: Config) -> tuple[dict, list[str], list[str]]:
    name = call.get("function", {}).get("name")
    if not isinstance(call.get("id"), str) or not call["id"]:
        raise ToolError("tool call must have a nonempty ID")
    if name not in schemas:
        raise ToolError(f"undeclared tool: {name}")
    schema = schemas[name]
    raw = call["function"].get("arguments", "")
    notes, initial_errors = [], []
    args: Any
    if isinstance(raw, dict):
        args = raw
        notes.append("arguments object → JSON string")
    elif isinstance(raw, str):
        try:
            args = json.loads(raw)
        except (ValueError, TypeError):
            initial_errors.append("malformed JSON")
            try:
                args = parse_repair(raw)
            except (ValueError, TypeError, RecursionError) as exc:
                raise ToolError("JSON cannot be repaired") from exc
            notes.append("repaired malformed JSON")
    else:
        raise ToolError("tool arguments must be a JSON object or encoded object")
    validator = Draft202012Validator(schema)
    initial_errors.extend(error.message for error in validator.iter_errors(args))
    args = coerce(args, schema, notes)
    errors = [error.message for error in validator.iter_errors(args)]
    if errors or not isinstance(args, dict):
        raise ToolError("; ".join(errors) or "tool arguments must be an object")
    enforce_policy(args, project, config, name)
    cleaned = {"id": call["id"], "type": "function", "function": {"name": name, "arguments": json.dumps(args, allow_nan=False)}}
    return cleaned, notes, initial_errors

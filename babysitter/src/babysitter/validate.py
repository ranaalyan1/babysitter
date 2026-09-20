"""Validate stage: is this action allowed and well-formed?

Checks, in order: tool exists → args parse as JSON → args fit the tool's
schema (required fields, no extras, correct types) → string paths are
safe (relative, inside the project root) → payload size sane.

Validation never mutates anything and never consults the model. Anything
it rejects goes to Repair (if mechanically fixable) or back to the model
as failure context (if not).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .toolspec import MAX_ARGS_BYTES, tool_spec

CODE_UNKNOWN_TOOL = "unknown-tool"
CODE_BAD_JSON = "bad-json"
CODE_MISSING_FIELD = "missing-field"
CODE_EXTRA_FIELD = "extra-field"
CODE_WRONG_TYPE = "wrong-type"
CODE_BAD_PATH = "bad-path"
CODE_PATH_ESCAPE = "path-escape"
CODE_ARG_TOO_LARGE = "arg-too-large"


@dataclass
class Issue:
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


@dataclass
class ValidationResult:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    args: dict | None = None  # parsed args when JSON was valid

    def issues_as_dicts(self) -> list[dict]:
        return [i.to_dict() for i in self.issues]


def _check_type(value: object, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True  # unknown schema type: don't invent failures


def check_path_safe(path_value: str, project_root: str | Path) -> Issue | None:
    """Paths must be relative and must resolve inside the project root."""
    if not path_value or not path_value.strip():
        return Issue(CODE_BAD_PATH, "path must be a non-empty string")
    if os.path.isabs(path_value):
        return Issue(CODE_BAD_PATH, f"absolute paths are not allowed: {path_value!r}")
    root = os.path.realpath(str(project_root))
    joined = os.path.normpath(os.path.join(root, path_value))
    if joined != root and not joined.startswith(root + os.sep):
        return Issue(
            CODE_PATH_ESCAPE,
            f"path escapes the project root: {path_value!r}",
        )
    return None


def validate_call(
    name: str,
    args_raw: str | dict,
    project_root: str | Path,
    specs: dict[str, dict] | None = None,
    check_paths: bool = True,
) -> ValidationResult:
    """Validate one tool call. ``args_raw`` is the model's raw argument
    string (or an already-parsed dict, e.g. from Anthropic tool_use input).

    ``specs`` overrides the tool registry: the protocol server passes the
    agent's own declared schemas so it can validate the agent's tools.
    ``check_paths`` enables filesystem-path containment checks; the
    protocol server disables it because it does not execute calls and
    cannot know which agent fields are really paths (the agent's own
    executor owns that check).
    """
    registry = specs if specs is not None else {n: tool_spec(n) for n in ("read_file", "write_file", "edit_file")}
    spec = registry.get(name)
    if spec is None:
        known = ", ".join(sorted(registry))
        return ValidationResult(
            ok=False,
            issues=[
                Issue(
                    CODE_UNKNOWN_TOOL,
                    f"unknown tool {name!r}; available: {known or '(none declared)'}",
                )
            ],
        )

    if isinstance(args_raw, dict):
        args = args_raw
        raw_len = len(json.dumps(args_raw))
    else:
        raw_len = len(args_raw.encode("utf-8", "replace"))
        args = None
    if raw_len > MAX_ARGS_BYTES:
        return ValidationResult(
            ok=False,
            issues=[
                Issue(
                    CODE_ARG_TOO_LARGE,
                    f"args payload is {raw_len} bytes (limit {MAX_ARGS_BYTES})",
                )
            ],
        )
    if args is None:
        assert isinstance(args_raw, str)
        try:
            parsed = json.loads(args_raw)
        except json.JSONDecodeError as exc:
            return ValidationResult(
                ok=False,
                issues=[
                    Issue(CODE_BAD_JSON, f"args are not valid JSON: {exc.msg} "
                           f"at position {exc.pos}")
                ],
            )
        if not isinstance(parsed, dict):
            return ValidationResult(
                ok=False,
                issues=[
                    Issue(
                        CODE_BAD_JSON,
                        "tool args must be a JSON object",
                    )
                ],
            )
        args = parsed

    issues: list[Issue] = []
    params = spec["parameters"]
    properties: dict = params.get("properties", {})
    required: list = params.get("required", [])

    for field_name in required:
        if field_name not in args:
            issues.append(
                Issue(
                    CODE_MISSING_FIELD,
                    f"missing required field {field_name!r} for tool {name!r}",
                )
            )
    for field_name, value in args.items():
        if field_name not in properties:
            issues.append(
                Issue(
                    CODE_EXTRA_FIELD,
                    f"unknown field {field_name!r} for tool {name!r}",
                )
            )
            continue
        expected = properties[field_name].get("type", "string")
        if not _check_type(value, expected):
            issues.append(
                Issue(
                    CODE_WRONG_TYPE,
                    f"field {field_name!r} must be {expected}, "
                    f"got {type(value).__name__}",
                )
            )

    # Path safety for every string field literally named "path".
    if (
        check_paths
        and "path" in properties
        and isinstance(args.get("path"), str)
    ):
        path_issue = check_path_safe(args["path"], project_root)
        if path_issue is not None:
            issues.append(path_issue)

    if issues:
        return ValidationResult(ok=False, issues=issues, args=args)
    return ValidationResult(ok=True, issues=[], args=args)

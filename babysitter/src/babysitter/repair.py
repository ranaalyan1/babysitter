"""Repair stage: fix recoverable mistakes before they execute.

Two layers:

1. :func:`heal_json` — mechanical JSON fixes (fences, trailing commas,
   unquoted keys, single quotes, bad literals, unclosed brackets).
2. :func:`repair_call` — schema-driven fixes on top (drop unknown fields,
   fill schema defaults, safe type coercions) plus re-validation.

Repair is transparent: every fix is named and logged (``repair.applied``
with ``fixes[]``), so the trace shows exactly what Babysitter changed.
Anything unfixable returns ``ok=False`` with a reason that becomes retry
context — never a silent guess (paths are never guessed, for example).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .toolspec import tool_spec
from .validate import ValidationResult, validate_call

FIX_STRIP_FENCES = "strip-fences"
FIX_EXTRACT_OBJECT = "extract-object"
FIX_TRAILING_COMMAS = "drop-trailing-commas"
FIX_QUOTE_KEYS = "quote-keys"
FIX_SINGLE_QUOTES = "single-to-double"
FIX_LITERALS = "fix-literals"
FIX_CLOSE_BRACKETS = "close-brackets"

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_UNQUOTED_KEY_RE = re.compile(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)')
_SINGLE_QUOTED_RE = re.compile(r"'([^'\\\n]*(?:\\.[^'\\\n]*)*)'")
_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_\"'])"
    r"(True|False|None|NaN|Infinity|undefined)"
    r"(?![A-Za-z0-9_\"'])"
)
_LITERAL_MAP = {
    "True": "true",
    "False": "false",
    "None": "null",
    "NaN": "null",
    "Infinity": "null",
    "undefined": "null",
}


def _try_parse(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _close_brackets(text: str) -> str:
    """Append missing closing brackets/braces, string-aware."""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    if in_string:
        text += '"'
    closers = {"{": "}", "[": "]"}
    while stack:
        text += closers[stack.pop()]
    return text


def heal_json(text: str) -> tuple[dict | None, list[str]]:
    """Try to parse ``text`` as a JSON object, applying mechanical fixes.

    Returns ``(parsed_dict_or_None, fixes_applied)``. Fixes are attempted
    cumulatively in catalog order; parsing is retried after each step.
    """
    fixes: list[str] = []
    parsed = _try_parse(text)
    if parsed is not None:
        return parsed, fixes

    candidate = text

    # 1. Markdown code fences.
    fence = _FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
        fixes.append(FIX_STRIP_FENCES)
        parsed = _try_parse(candidate)
        if parsed is not None:
            return parsed, fixes

    # 2. Prose around the object: first "{" through last "}".
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        extracted = candidate[start : end + 1]
        if extracted != candidate:
            candidate = extracted
            fixes.append(FIX_EXTRACT_OBJECT)
            parsed = _try_parse(candidate)
            if parsed is not None:
                return parsed, fixes

    # 3. Trailing commas.
    no_trailing = _TRAILING_COMMA_RE.sub(r"\1", candidate)
    if no_trailing != candidate:
        candidate = no_trailing
        fixes.append(FIX_TRAILING_COMMAS)
        parsed = _try_parse(candidate)
        if parsed is not None:
            return parsed, fixes

    # 4. Unquoted keys.
    quoted = _UNQUOTED_KEY_RE.sub(r'\1"\2"\3', candidate)
    if quoted != candidate:
        candidate = quoted
        fixes.append(FIX_QUOTE_KEYS)
        parsed = _try_parse(candidate)
        if parsed is not None:
            return parsed, fixes

    # 5. Single-quoted strings (only when they contain no double quotes,
    #    so we never corrupt already-valid inner content).
    def _requote(match: "re.Match[str]") -> str:
        inner = match.group(1).replace('"', '\\"')
        return f'"{inner}"'

    resingle = _SINGLE_QUOTED_RE.sub(_requote, candidate)
    if resingle != candidate:
        candidate = resingle
        fixes.append(FIX_SINGLE_QUOTES)
        parsed = _try_parse(candidate)
        if parsed is not None:
            return parsed, fixes

    # 6. Python/JS literals.
    relit = _LITERAL_RE.sub(lambda m: _LITERAL_MAP[m.group(1)], candidate)
    if relit != candidate:
        candidate = relit
        fixes.append(FIX_LITERALS)
        parsed = _try_parse(candidate)
        if parsed is not None:
            return parsed, fixes

    # 7. Unclosed brackets/braces.
    closed = _close_brackets(candidate)
    if closed != candidate:
        candidate = closed
        fixes.append(FIX_CLOSE_BRACKETS)
        parsed = _try_parse(candidate)
        if parsed is not None:
            return parsed, fixes

    return None, fixes


def _coerce(value: object, expected: str) -> tuple[object, bool]:
    """Safe, narrow type coercions. Returns (value, changed)."""
    if expected == "string" and isinstance(value, (int, float, bool)):
        return (str(value).lower() if isinstance(value, bool) else str(value)), True
    if expected == "integer" and isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[+-]?\d+", text):
            return int(text), True
    if expected == "number" and isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", text):
            return float(text), True
    if expected == "boolean" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1"):
            return True, True
        if lowered in ("false", "0"):
            return False, True
    return value, False


@dataclass
class RepairResult:
    ok: bool
    args: dict | None = None
    fixes: list[str] = field(default_factory=list)
    reason: str = ""


def repair_call(
    name: str,
    args_raw: str | dict,
    project_root: str | Path,
    specs: dict[str, dict] | None = None,
    check_paths: bool = True,
) -> RepairResult:
    """Attempt to turn a failed-validation call into a valid one.

    ``specs`` / ``check_paths`` behave as in :func:`validate.validate_call`.
    """
    if specs is not None:
        spec = specs.get(name)
    else:
        spec = tool_spec(name)
    if spec is None:
        return RepairResult(ok=False, reason=f"unknown tool {name!r}")

    fixes: list[str] = []
    if isinstance(args_raw, dict):
        args = dict(args_raw)
    else:
        healed, fixes = heal_json(args_raw)
        if healed is None:
            detail = ", ".join(fixes) if fixes else "no fix applied"
            return RepairResult(
                ok=False, reason=f"args are not parseable as JSON ({detail})"
            )
        args = healed

    properties: dict = spec["parameters"].get("properties", {})
    required: list = spec["parameters"].get("required", [])

    for field_name in list(args):
        if field_name not in properties:
            del args[field_name]
            fixes.append(f"drop-extra:{field_name}")

    for field_name in required:
        if field_name not in args:
            default = properties.get(field_name, {}).get("default")
            if default is None:
                return RepairResult(
                    ok=False,
                    reason=f"missing required field {field_name!r} "
                    "and no schema default exists",
                )
            args[field_name] = default
            fixes.append(f"default:{field_name}")

    for field_name, value in list(args.items()):
        expected = properties.get(field_name, {}).get("type", "string")
        coerced, changed = _coerce(value, expected)
        if changed:
            args[field_name] = coerced
            fixes.append(
                f"coerce:{field_name}:{type(value).__name__}->{expected}"
            )

    recheck: ValidationResult = validate_call(
        name, args, project_root, specs=specs, check_paths=check_paths
    )
    if not recheck.ok:
        problems = "; ".join(i.message for i in recheck.issues)
        return RepairResult(ok=False, reason=f"still invalid after repair: {problems}")
    return RepairResult(ok=True, args=args, fixes=fixes)

"""Execute stage: run validated tool calls against the project tree.

Only the v0.1 minimal toolset (read_file / write_file / edit_file).
Assumes calls were already validated — but re-checks path containment
anyway (defense in depth: the executor never trusts its caller).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Cap on bytes returned to the model for a single read.
MAX_READ_BYTES = 64 * 1024


@dataclass
class ToolExecResult:
    ok: bool
    output: str = ""
    error: str = ""
    touched: list[str] = field(default_factory=list)  # project-relative paths written


def _resolve(root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` inside ``root``; None if it escapes or is absolute."""
    if not rel or os.path.isabs(rel):
        return None
    joined = os.path.normpath(os.path.join(str(root), rel))
    real_root = os.path.realpath(str(root))
    if joined != real_root and not joined.startswith(real_root + os.sep):
        return None
    return Path(joined)


def execute_tool(name: str, args: dict, project_root: str | Path) -> ToolExecResult:
    root = Path(project_root)
    if name == "read_file":
        return _read(root, args.get("path", ""))
    if name == "write_file":
        return _write(root, args.get("path", ""), args.get("content", ""))
    if name == "edit_file":
        return _edit(root, args.get("path", ""), args.get("old_text", ""),
                     args.get("new_text", ""))
    return ToolExecResult(ok=False, error=f"cannot execute unknown tool {name!r}")


def _read(root: Path, rel: str) -> ToolExecResult:
    target = _resolve(root, rel) if isinstance(rel, str) else None
    if target is None:
        return ToolExecResult(ok=False, error=f"unsafe path: {rel!r}")
    if not target.is_file():
        return ToolExecResult(ok=False, error=f"file not found: {rel}")
    try:
        data = target.read_bytes()
    except OSError as exc:
        return ToolExecResult(ok=False, error=f"read failed: {exc}")
    text = data.decode("utf-8", "replace")
    if len(data) > MAX_READ_BYTES:
        text = text[:MAX_READ_BYTES] + "\n…[truncated: file exceeds 64 KiB]…"
    return ToolExecResult(ok=True, output=text)


def _write(root: Path, rel: str, content: str) -> ToolExecResult:
    target = _resolve(root, rel) if isinstance(rel, str) else None
    if target is None:
        return ToolExecResult(ok=False, error=f"unsafe path: {rel!r}")
    if not isinstance(content, str):
        return ToolExecResult(ok=False, error="content must be a string")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return ToolExecResult(ok=False, error=f"write failed: {exc}")
    return ToolExecResult(ok=True, output=f"wrote {rel} ({len(content)} chars)",
                          touched=[rel])


def _edit(root: Path, rel: str, old_text: str, new_text: str) -> ToolExecResult:
    target = _resolve(root, rel) if isinstance(rel, str) else None
    if target is None:
        return ToolExecResult(ok=False, error=f"unsafe path: {rel!r}")
    if not target.is_file():
        return ToolExecResult(ok=False, error=f"file not found: {rel}")
    if not isinstance(old_text, str) or not old_text:
        return ToolExecResult(ok=False, error="old_text must be a non-empty string")
    if not isinstance(new_text, str):
        return ToolExecResult(ok=False, error="new_text must be a string")
    try:
        current = target.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolExecResult(ok=False, error=f"read failed: {exc}")
    matches = current.count(old_text)
    if matches == 0:
        return ToolExecResult(ok=False, error="old_text not found in file")
    if matches > 1:
        return ToolExecResult(
            ok=False, error=f"old_text is ambiguous ({matches} matches); "
            "include more context"
        )
    try:
        target.write_text(current.replace(old_text, new_text, 1), encoding="utf-8")
    except OSError as exc:
        return ToolExecResult(ok=False, error=f"write failed: {exc}")
    return ToolExecResult(ok=True, output=f"edited {rel}", touched=[rel])

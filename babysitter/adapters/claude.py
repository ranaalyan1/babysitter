"""Claude Code hook entry point; concrete decisions use the shared native lifecycle."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ..config import Config
from ..project import Project
from ..state import Store
from .claude_install import EVENTS
from .native import (MAX_INPUT, CONTROL_FILES, NATIVE_SCHEMAS, TOOL_EVENTS, HookError,
                     NativeHookAdapter, context, deny, halt, parse_event, project_lock)


class ClaudeAdapter(NativeHookAdapter):
    """Claude Code-specific identity; v0.2 state tables and CLI stay compatible."""


def hook_error(event: str, exc: Exception, store: Store | None = None, adapter: NativeHookAdapter | None = None,
               payload: dict | None = None, session_table: str = "claude_sessions") -> dict:
    message = f"{type(exc).__name__}: {exc}. No verified completion was recorded by this callback."
    if store:
        try:
            task_id = adapter.task_id if adapter else None
            if not task_id and payload:
                row = store.db.execute(f"SELECT task_id FROM {session_table} WHERE session_id=?", (payload["session_id"],)).fetchone()
                task_id = row[0] if row else None
            if task_id:
                store.event(task_id, "recover", "failure", {"class": "unsafe-change", "context": message, "worktree_retained": True}, state="failed")
        except Exception:
            pass  # Persistence failure must still produce a blocking decision.
    print("Babysitter hook error: " + message, file=sys.stderr)
    if event == "PreToolUse":
        return deny(message)
    if event == "UserPromptSubmit":
        return {"decision": "block", "reason": "Babysitter: NOT VERIFIED. " + message}
    return halt(message)


def hook_main(root: Path, event: str, data: bytes) -> int:
    try:
        if len(data) > MAX_INPUT:
            raise HookError("Hook input exceeds 2 MB")
        payload = parse_event(json.loads(data), event, root)
        with project_lock(root):
            store = Store(root / ".babysitter")
            adapter = None
            try:
                config = Config.load(root)
                project = Project(root, store, config.max_snapshot_bytes)
                adapter = ClaudeAdapter(project, store, config)
                async def dispatch():
                    # Finish before the installed hook deadline, including command cleanup.
                    timeout = 3 * config.command_timeout + 45 if event == "Stop" else 8 if event == "SessionEnd" else 45
                    return await asyncio.wait_for(adapter.handle(payload), timeout=timeout)
                result = asyncio.run(dispatch())
            except Exception as exc:
                # Record terminal failure before releasing the lock to another callback.
                result = hook_error(event, exc, store, adapter, payload)
            finally:
                store.close()
    except Exception as exc:
        result = hook_error(event, exc)
    print(json.dumps(result, ensure_ascii=True))
    return 0  # Structured decisions, not non-blocking Unix exit 1.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Babysitter's installed Claude Code hook handler")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--event", choices=EVENTS, required=True)
    args = parser.parse_args(argv)
    return hook_main(args.root.resolve(), args.event, sys.stdin.buffer.read(MAX_INPUT + 1))


if __name__ == "__main__":
    raise SystemExit(main())

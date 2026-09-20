"""Concrete Codex hook wire contract; shared evidence/recovery, native permissions."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
import sys
from pathlib import Path

from ..config import Config
from ..project import Project
from ..state import Store, TERMINAL, redact
from .claude import hook_error
from .codex_install import EVENTS
from .native import MAX_INPUT, HookError, NativeHookAdapter, context, deny, parse_event, project_lock


class CodexAdapter(NativeHookAdapter):
    adapter_name = "codex"
    agent_label = "Codex"
    event_prefix = "codex"
    session_table = "codex_sessions"
    call_table = "codex_calls"
    schema_file = "codex_schema.sql"
    control_files = ("babysitter.json", ".gitignore", ".codex/hooks.json", ".codex/config.toml", ".claude/settings.local.json", ".claude/settings.json")

    def validate_tool(self, name: str, arguments: dict) -> tuple[dict, list[str]]:
        if name.rsplit(".", 1)[-1] in {"spawn_agent", "send_input", "resume_agent", "wait_agent", "close_agent"} or name.startswith("multi_agent"):
            raise HookError("Subagent orchestration is not supervised by this single-agent adapter")
        if name == "apply_patch":
            patch = arguments.get("command")
            if not isinstance(patch, str):
                raise HookError("Codex apply_patch requires a string tool_input.command")
            lines = patch.strip().splitlines()
            if len(lines) < 3 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
                raise HookError("Patch must have the complete native Begin Patch / End Patch envelope")
            changes = 0
            for line in lines[1:-1]:
                match = re.fullmatch(r"\*\*\* (Add File|Update File|Delete File|Move to): (.+)", line)
                if match:
                    # Validate every source AND rename destination. Do not execute or
                    # rewrite a native patch using our own edit implementation.
                    super().validate_tool("Write", {"file_path": match[2], "content": ""})
                    changes += match[1] != "Move to"
                elif line.startswith(("*** Add File", "*** Update File", "*** Delete File", "*** Move to")):
                    raise HookError("Malformed patch path header")
            if not changes:
                raise HookError("Patch contains no recognized file changes")
            return copy.deepcopy(arguments), []
        cleaned, repairs = super().validate_tool(name, arguments)
        if repairs:
            raise HookError("Retry with schema-correct argument types. Codex input rewrites require an allow decision; Babysitter does not auto-approve tools")
        return cleaned, []

    async def handle(self, payload: dict) -> dict:
        original_event = payload["hook_event_name"]
        if original_event == "UserPromptSubmit":
            session = self.session(payload["session_id"])
            if session["task_id"]:
                task = self.store.task(session["task_id"])
                if task["state"] not in TERMINAL:
                    retry = next((e["payload"] for e in reversed(self.events(task["id"])) if e["kind"] == "codex.stop.blocked"), None)
                    if retry and payload["prompt"] == retry["instruction"]:
                        self.task_id = task["id"]
                        self.guard_controls(task["id"])
                        self.store.event(task["id"], "observe", "codex.continuation.resumed", {"turn_id": payload.get("turn_id"), "same_task": True})
                        return context("UserPromptSubmit", "Babysitter recovery continues the same task, checkpoint and retry budget. The previous failed patch was not successful completion.")
            payload = {**payload, "prompt_id": payload.get("turn_id")}
        if original_event == "PostToolUse":
            result = payload.get("tool_response")
            text = result if isinstance(result, str) else str(result.get("output", "")) if isinstance(result, dict) else ""
            if payload["tool_name"] == "Bash" and ((isinstance(result, dict) and result.get("running") is True) or "Process running with session ID" in text):
                session = self.session(payload["session_id"])
                if not session["task_id"]:
                    raise HookError("Running native process has no supervised task")
                self.task_id = session["task_id"]
                self.guard_controls(session["task_id"])
                call = self.store.db.execute("SELECT * FROM codex_calls WHERE task_id=? AND tool_use_id=?", (session["task_id"], payload["tool_use_id"])).fetchone()
                if not call or call["state"] != "pending" or call["tool_name"] != "Bash" or call["input_json"] != json.dumps(redact(payload["tool_input"]), sort_keys=True):
                    raise HookError("Running command has no matching pending pre-tool callback")
                self.store.event(self.task_id, "observe", "codex.tool.incomplete", {"tool_use_id": payload["tool_use_id"], "reason": "Native command still running; matching call remains pending"})
                return context("PostToolUse", "Native command is still running. Poll it to completion; Babysitter will not verify or roll back while callbacks are pending.")
            explicit_error = isinstance(result, dict) and (result.get("isError") is True or result.get("is_error") is True
                              or result.get("exit_code", result.get("exitCode", 0)) not in (0, None))
            if payload["tool_name"] == "Bash":
                match = re.search(r"(?:Process exited with code|Exit code:)\s*(-?\d+)", text)
                explicit_error = explicit_error or bool(match and int(match[1]) != 0)
            if explicit_error:
                payload = {**payload, "hook_event_name": "PostToolUseFailure", "error": result}
        output = await super().handle(payload)
        if original_event == "Stop" and output.get("decision") == "block" and self.task_id:
            self.store.event(self.task_id, "recover", "codex.stop.blocked", {"instruction": output["reason"], "turn_id": payload.get("turn_id")})
        if "hookSpecificOutput" in output:
            output["hookSpecificOutput"]["hookEventName"] = original_event
        # Unlike Claude, Codex reports universal halt fields on PreToolUse as an
        # unsupported shape and continues the call. Always emit a supported deny.
        if original_event == "PreToolUse" and output.get("continue") is False:
            return deny(output["stopReason"])
        return output


def teardown(store: Store, payload: dict) -> dict:
    """Advisory native exit hooks have a hard 3s ceiling: no subprocess/snapshot."""
    store.db.executescript(Path(__file__).parents[1].joinpath("codex_schema.sql").read_text())
    row = store.db.execute("SELECT task_id FROM codex_sessions WHERE session_id=?", (payload["session_id"],)).fetchone()
    if row and row[0]:
        task = store.task(row[0])
        store.event(task["id"], "observe", "codex.session.ended", {"event": payload["hook_event_name"], "worktree_retained": True})
        if task["state"] not in TERMINAL:
            store.event(task["id"], "observe", "task.finished", {"state": "failed", "adapter": "codex", "reason": "Native session ended/interrupted before verified completion; files retained"}, state="failed")
    return {}


def hook_main(root: Path, event: str, data: bytes) -> int:
    try:
        if len(data) > MAX_INPUT:
            raise HookError("Hook input exceeds 2 MB")
        payload = parse_event(json.loads(data), event, root, EVENTS)
        short = event in {"SessionEnd", "Interrupt"}
        with project_lock(root, timeout_seconds=1 if short else 5):
            store = Store(root / ".babysitter", timeout=0.2 if short else 5)
            adapter = None
            try:
                if short:
                    result = teardown(store, payload)
                else:
                    config = Config.load(root)
                    project = Project(root, store, config.max_snapshot_bytes)
                    adapter = CodexAdapter(project, store, config)
                    async def dispatch():
                        return await asyncio.wait_for(adapter.handle(payload), 3 * config.command_timeout + 45 if event == "Stop" else 45)
                    result = asyncio.run(dispatch())
            except Exception as exc:
                result = hook_error(event, exc, store, adapter, payload, "codex_sessions")
            finally:
                store.close()
    except Exception as exc:
        result = hook_error(event, exc)
    if event in {"SessionEnd", "Interrupt"} and result.get("continue") is False:
        result = {"systemMessage": result["stopReason"]}  # Advisory, no unsupported control fields.
    print(json.dumps(result, ensure_ascii=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Installed Babysitter Codex hook handler")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--event", required=True, choices=EVENTS)
    args = parser.parse_args(argv)
    return hook_main(args.root.resolve(), args.event, sys.stdin.buffer.read(MAX_INPUT + 1))


if __name__ == "__main__":
    raise SystemExit(main())

"""Protocol server (Layer 1): `/v1/messages`, `/v1/chat/completions`,
`/v1/models`.

An HTTP proxy alone cannot see everything inside Cursor/Claude Code —
Babysitter does not pretend otherwise. In server mode, supervision is
exactly:

1. what passes through the protocol layer (model responses get
   validate → repair before reaching the agent; the agent never sees
   the mess), plus
2. what the verification engine independently observes (tree
   fingerprint diff + test/typecheck runs between turns; failures are
   injected as context into the next forwarded turn), plus
3. tier escalation on consecutive failing turns.

Babysitter owns model selection (the agent's requested model id is
accepted but the serving tier decides) and never executes tools here —
the external agent does. Server-mode tasks stay ``in_progress``:
completion judgment belongs to the supervised loop (loop.py) in v0.1.

Validation in server mode is well-formedness against the AGENT's own
declared schemas (OpenAI function shape); path-containment checks are
skipped because the agent's executor owns path safety.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from . import __version__
from .escalate import EscalationManager
from .provider import ModelTurn, Provider, ProviderError
from .repair import repair_call
from .schema import (
    KIND_ESCALATION_SKIPPED,
    KIND_ESCALATION_TRIGGERED,
    KIND_MODEL_TURN,
    KIND_REPAIR_APPLIED,
    KIND_REPAIR_FAILED,
    KIND_TOOL_CALL_OBSERVED,
    KIND_TOOL_RESULT_OBSERVED,
    KIND_VALIDATION_FAILED,
    KIND_VALIDATION_PASSED,
    KIND_VERIFICATION_FAILED,
    KIND_VERIFICATION_PASSED,
    KIND_VERIFICATION_STARTED,
    KIND_VERIFICATION_UNAVAILABLE,
    STAGE_ESCALATE,
    STAGE_OBSERVE,
    STAGE_REPAIR,
    STAGE_VALIDATE,
    STAGE_VERIFY,
    STATUS_IN_PROGRESS,
)
from .store import BabysitterStore
from .validate import validate_call
from .verify import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VerificationEngine,
)

ERROR_HINTS = ("error", "failed", "failure", "exception", "traceback")


def _tail(text: str, limit: int = 2000) -> str:
    text = text or ""
    return text if len(text) <= limit else "…" + text[-limit:]


def tool_result_failed(content: str) -> bool:
    """Heuristic: does a tool result look like an error? Documented as a
    heuristic — used only for escalation counting and observed-ok flags."""
    lowered = (content or "").lower()
    return any(hint in lowered for hint in ERROR_HINTS)


def tree_fingerprint(
    root: str | Path, extra_ignored: set[str] | None = None
) -> dict[str, str]:
    """Map of project-relative path → sha256 for change detection.

    ``extra_ignored`` holds project-relative paths to skip (used for the
    state db itself: it churns on every request, and without this every
    turn would "detect changes" and re-verify).
    """
    from .recover import IGNORED_NAMES

    out: dict[str, str] = {}
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_NAMES]
        for name in filenames:
            full = Path(dirpath) / name
            rel = str(full.relative_to(root))
            if extra_ignored and rel in extra_ignored:
                continue
            try:
                digest = hashlib.sha256()
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        digest.update(chunk)
                out[rel] = digest.hexdigest()
            except OSError:
                continue
    return out


def fingerprint_diff(
    old: dict[str, str], new: dict[str, str]
) -> list[str]:
    changed = [p for p, h in new.items() if old.get(p) != h]
    changed += [p for p in old if p not in new]
    return sorted(changed)


@dataclass
class SessionState:
    task_id: str
    escalation: EscalationManager
    last_fingerprint: dict[str, str] = field(default_factory=dict)


@dataclass
class ServerConfig:
    project_root: str
    db_path: str
    providers: dict[str, Provider]  # ladder model id -> provider
    ladder: list[str]
    verify: dict = field(default_factory=dict)
    escalation_threshold: int = 2


def create_app(config: ServerConfig) -> FastAPI:
    missing = [m for m in config.ladder if m not in config.providers]
    if missing:
        raise ValueError(f"no provider configured for ladder models: {missing}")
    verify_engine = VerificationEngine(config.verify)
    sessions: dict[str, SessionState] = {}
    lock = threading.Lock()

    # Never treat our own state db (which churns every request) as an
    # agent-made change. Normally it lives under .babysitter/ (already
    # ignored); this covers custom db paths too.
    try:
        _db_rel = os.path.relpath(config.db_path, config.project_root)
    except ValueError:
        _db_rel = ""
    if _db_rel.startswith(".."):
        _db_rel = ""
    _ignored_db_files = (
        {_db_rel, _db_rel + "-wal", _db_rel + "-shm", _db_rel + "-journal"}
        if _db_rel
        else set()
    )

    def fingerprint() -> dict[str, str]:
        return tree_fingerprint(config.project_root, _ignored_db_files)

    app = FastAPI(title="babysitter", version=__version__)

    def get_store() -> BabysitterStore:
        # One connection per request: SQLite connections are not thread-safe.
        return BabysitterStore(config.db_path)

    def get_session(session_id: str) -> SessionState:
        with lock:
            state = sessions.get(session_id)
            if state is None:
                store = get_store()
                try:
                    task = store.create_task(
                        goal=f"protocol session {session_id}",
                        project_root=config.project_root,
                        model=config.ladder[0],
                        config={"ladder": list(config.ladder), "mode": "server"},
                    )
                    store.set_task_status(task.id, STATUS_IN_PROGRESS)
                    state = SessionState(
                        task_id=task.id,
                        escalation=EscalationManager(
                            list(config.ladder),
                            threshold=config.escalation_threshold,
                        ),
                        last_fingerprint=fingerprint(),
                    )
                    sessions[session_id] = state
                finally:
                    store.close()
            return state

    def observe_incoming_tool_results(
        store: BabysitterStore, task_id: str, messages: list[dict]
    ) -> int:
        """Log tool results the agent sends back; return error count."""
        errors = 0
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content)
            failed = tool_result_failed(content)
            errors += 1 if failed else 0
            store.log_event(
                task_id, STAGE_OBSERVE, KIND_TOOL_RESULT_OBSERVED,
                f"tool result observed ({'error' if failed else 'ok'})",
                {"call_id": msg.get("tool_call_id", ""),
                 "name": "",
                 "ok": not failed,
                 "result_tail": _tail(content, 500)},
            )
        return errors

    def verify_between_turns(
        store: BabysitterStore, state: SessionState
    ) -> dict | None:
        """Diff the tree; verify if it changed. Returns a system message
        with failure context when verification fails, else None."""
        current = fingerprint()
        changed = fingerprint_diff(state.last_fingerprint, current)
        state.last_fingerprint = current
        if not changed:
            return None
        store.log_event(
            state.task_id, STAGE_VERIFY, KIND_VERIFICATION_STARTED,
            "verification started (post-change)",
            {"trigger": "post-change", "files_changed": changed[:50]},
        )
        report = verify_engine.run(config.project_root)
        if report.verdict == VERDICT_PASS:
            store.log_event(
                state.task_id, STAGE_VERIFY, KIND_VERIFICATION_PASSED,
                "verification passed", report.to_payload())
            return None
        if report.verdict == VERDICT_FAIL:
            store.log_event(
                state.task_id, STAGE_VERIFY, KIND_VERIFICATION_FAILED,
                f"verification failed ({report.failed_check})",
                report.to_payload())
            return {
                "role": "system",
                "content": (
                    "Babysitter verification FAILED on your latest changes "
                    f"({report.failed_check}). Fix the code (not the tests) "
                    "before continuing. Failure output (truncated):\n"
                    + report.tail[-2000:]
                ),
            }
        store.log_event(
            state.task_id, STAGE_VERIFY, KIND_VERIFICATION_UNAVAILABLE,
            f"verification unavailable: {report.unavailable_reason[:200]}",
            report.to_payload())
        return {
            "role": "system",
            "content": (
                "Babysitter could not verify your latest changes: "
                f"{report.unavailable_reason}. Proceed only if you can "
                "verify them yourself."
            ),
        }

    def supervise_response(
        store: BabysitterStore,
        task_id: str,
        turn: ModelTurn,
        declared_specs: dict[str, dict],
    ) -> list[dict]:
        """Validate → repair each tool call; return OpenAI tool_calls with
        repaired args substituted. The agent receives clean calls."""
        out_calls: list[dict] = []
        for i, call in enumerate(turn.tool_calls):
            call_id = call.call_id or f"call-{i}"
            store.log_event(
                task_id, STAGE_OBSERVE, KIND_TOOL_CALL_OBSERVED,
                f"observed call {call.name}",
                {"call_id": call_id, "name": call.name,
                 "args_raw_tail": _tail(call.args_raw or "")},
            )
            result = validate_call(
                call.name, call.args_raw, config.project_root,
                specs=declared_specs, check_paths=False,
            )
            args_raw = call.args_raw
            if result.ok:
                store.log_event(
                    task_id, STAGE_VALIDATE, KIND_VALIDATION_PASSED,
                    f"validation passed for {call.name}",
                    {"call_id": call_id, "name": call.name})
            else:
                store.log_event(
                    task_id, STAGE_VALIDATE, KIND_VALIDATION_FAILED,
                    f"validation failed for {call.name}",
                    {"call_id": call_id, "name": call.name,
                     "issues": result.issues_as_dicts()})
                repaired = repair_call(
                    call.name, call.args_raw, config.project_root,
                    specs=declared_specs, check_paths=False,
                )
                if repaired.ok and repaired.args is not None:
                    args_raw = json.dumps(repaired.args)
                    store.log_event(
                        task_id, STAGE_REPAIR, KIND_REPAIR_APPLIED,
                        f"repaired {call.name}: {', '.join(repaired.fixes)}",
                        {"call_id": call_id, "name": call.name,
                         "fixes": repaired.fixes,
                         "args_tail": _tail(args_raw)})
                else:
                    store.log_event(
                        task_id, STAGE_REPAIR, KIND_REPAIR_FAILED,
                        f"could not repair {call.name}: {repaired.reason[:200]}",
                        {"call_id": call_id, "name": call.name,
                         "reason": repaired.reason})
            out_calls.append(
                {"id": call_id, "type": "function",
                 "function": {"name": call.name, "arguments": args_raw}}
            )
        return out_calls

    def apply_escalation(
        store: BabysitterStore, state: SessionState, turn_had_failure: bool
    ) -> None:
        if not turn_had_failure:
            state.escalation.note_success()
            return
        decision = state.escalation.note_failure("main")
        if decision.escalate:
            store.log_event(
                state.task_id, STAGE_ESCALATE, KIND_ESCALATION_TRIGGERED,
                f"escalated to {decision.to_model}",
                {"from_model": store.get_task(state.task_id).model,  # type: ignore[union-attr]
                 "to_model": decision.to_model, "step": 1,
                 "consecutive_failures": config.escalation_threshold})
            store.set_task_model(state.task_id, decision.to_model)
        elif decision.reason:
            store.log_event(
                state.task_id, STAGE_ESCALATE, KIND_ESCALATION_SKIPPED,
                f"escalation skipped: {decision.reason}",
                {"reason": decision.reason, "step": 1})

    def openai_specs_from_tools_param(tools_param: list[dict]) -> dict[str, dict]:
        specs: dict[str, dict] = {}
        for item in tools_param or []:
            fn = (item or {}).get("function", {})
            if fn.get("name"):
                specs[fn["name"]] = {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object"}),
                }
        return specs

    def run_supervised_turn(
        state: SessionState,
        store: BabysitterStore,
        messages: list[dict],
        tools_param: list[dict],
    ) -> tuple[ModelTurn, list[dict]]:
        """Shared core for both protocol adapters. Returns (turn,
        repaired OpenAI-shaped tool_calls)."""
        store.log_event(
            state.task_id, STAGE_OBSERVE, KIND_MODEL_TURN,
            "protocol turn",
            {"model": state.escalation.current_model, "step": 1,
             "content_tail": _tail(str(messages[-1]) if messages else ""),
             "tool_call_count": 0, "tool_call_names": []},
        )
        tool_errors = observe_incoming_tool_results(store, state.task_id, messages)
        failure_context = verify_between_turns(store, state)
        forwarded = ([failure_context] if failure_context else []) + list(messages)

        provider: Provider = config.providers[state.escalation.current_model]
        turn = provider.complete(forwarded, tools_param)  # may raise ProviderError

        declared = openai_specs_from_tools_param(tools_param)
        out_calls = supervise_response(store, state.task_id, turn, declared)
        apply_escalation(
            store, state, tool_errors > 0 or failure_context is not None)
        return turn, out_calls

    # -- routes -----------------------------------------------------------

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                {"id": model_id, "object": "model", "owned_by": "babysitter"}
                for model_id in config.ladder
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        x_babysitter_session: str | None = Header(default=None),
    ):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if body.get("stream"):
            return JSONResponse(
                {"error": "streaming is not supported in v0.1 (use stream=false)"},
                status_code=400,
            )
        messages = body.get("messages", [])
        tools_param = body.get("tools", []) or []
        if not isinstance(messages, list):
            return JSONResponse({"error": "messages must be a list"},
                                status_code=400)

        state = get_session(x_babysitter_session or "default")
        store = get_store()
        try:
            try:
                turn, out_calls = run_supervised_turn(
                    state, store, messages, tools_param)
            except ProviderError as exc:
                return JSONResponse({"error": f"provider failed: {exc}"},
                                    status_code=502)
            message: dict = {"role": "assistant", "content": turn.content or None}
            finish = "stop"
            if out_calls:
                message["tool_calls"] = out_calls
                finish = "tool_calls"
            return {
                "id": f"chatcmpl-babysitter-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": 0,
                "model": state.escalation.current_model,
                "choices": [{"index": 0, "message": message,
                             "finish_reason": finish}],
            }
        finally:
            store.close()

    @app.post("/v1/messages")
    async def anthropic_messages(
        request: Request,
        x_babysitter_session: str | None = Header(default=None),
    ):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(
                {"type": "error",
                 "error": {"type": "invalid_request_error",
                           "message": "invalid JSON body"}},
                status_code=400,
            )
        if body.get("stream"):
            return JSONResponse(
                {"type": "error",
                 "error": {"type": "invalid_request_error",
                           "message": "streaming is not supported in v0.1"}},
                status_code=400,
            )
        try:
            in_messages, in_tools = anthropic_to_openai(body)
        except ValueError as exc:
            return JSONResponse(
                {"type": "error",
                 "error": {"type": "invalid_request_error", "message": str(exc)}},
                status_code=400,
            )

        state = get_session(x_babysitter_session or "default")
        store = get_store()
        try:
            try:
                turn, out_calls = run_supervised_turn(
                    state, store, in_messages, in_tools)
            except ProviderError as exc:
                return JSONResponse(
                    {"type": "error",
                     "error": {"type": "api_error",
                               "message": f"provider failed: {exc}"}},
                    status_code=502)
            return openai_to_anthropic(
                turn, out_calls, state.escalation.current_model)
        finally:
            store.close()

    return app


# ---------------------------------------------------------------------------
# Anthropic Messages <-> OpenAI Chat translation (text + tool blocks only).
# ---------------------------------------------------------------------------

def _flatten_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block))
        return "\n".join(parts)
    return json.dumps(content)


def anthropic_to_openai(body: dict) -> tuple[list[dict], list[dict]]:
    """Convert an Anthropic Messages request to (openai_messages,
    openai_tools). Raises ValueError on unsupported blocks."""
    messages: list[dict] = []
    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": _flatten_content(system)})
    for msg in body.get("messages", []):
        role = msg.get("role")
        content = msg.get("content", "")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        text_parts: list[str] = []
        for block in content:
            btype = (block or {}).get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                if text_parts:
                    messages.append({"role": role, "content": "\n".join(text_parts)})
                    text_parts = []
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }],
                })
            elif btype == "tool_result":
                if text_parts:
                    messages.append({"role": role, "content": "\n".join(text_parts)})
                    text_parts = []
                messages.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": _flatten_content(block.get("content", "")),
                })
            else:
                raise ValueError(
                    f"unsupported content block type: {btype!r} "
                    "(v0.1 supports text, tool_use, tool_result)")
        if text_parts:
            messages.append({"role": role, "content": "\n".join(text_parts)})
    tools: list[dict] = []
    for tool in body.get("tools", []) or []:
        tools.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object"}),
            },
        })
    return messages, tools


def openai_to_anthropic(
    turn: ModelTurn, out_calls: list[dict], model: str
) -> dict:
    """Convert a supervised turn to an Anthropic Messages response."""
    content: list[dict] = []
    if turn.content:
        content.append({"type": "text", "text": turn.content})
    stop_reason = "end_turn"
    for call in out_calls:
        stop_reason = "tool_use"
        raw_args = call["function"]["arguments"]
        try:
            tool_input = json.loads(raw_args)
        except ValueError:
            # Unrepaired args are still not valid JSON: wrap them so the
            # response stays schema-valid while staying honest.
            tool_input = {"_raw": raw_args, "_babysitter_repair": "failed"}
        content.append({
            "type": "tool_use",
            "id": call["id"],
            "name": call["function"]["name"],
            "input": tool_input,
        })
    return {
        "id": f"msg_babysitter_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": model,
        "stop_reason": stop_reason,
        # Token accounting is not in v0.1; zeros, documented.
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }

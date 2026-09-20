from __future__ import annotations

import fcntl
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .config import Config
from .project import Project
from .protocol import anthropic_response, normalize, stream_events
from .provider import OpenAIProvider, ProviderError
from .repair import ToolError
from .runtime import Runtime, SupervisionError
from .state import Store


def create_app(root: Path | str = ".", config: Config | None = None, provider=None) -> FastAPI:
    root = Path(root).resolve()
    config = config or Config.load(root)
    config.validate()
    store = Store(root / ".aletheia")
    project = Project(root, store, config.max_snapshot_bytes)
    upstream = provider or OpenAIProvider(config)
    runtime = Runtime(project, store, config, upstream)
    token = os.environ.get(config.token_env)

    @asynccontextmanager
    async def lifespan(app):
        with (root / ".aletheia" / "runtime.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("A Aletheia runtime already owns this project")
            try:
                # An interrupted managed turn is not a success and must not own the
                # project forever. Retain all bytes for operator inspection, never
                # auto-rollback changes that may have been edited while offline.
                trace = store.trace()
                native_tasks = {event["task_id"]: event["payload"]["adapter"] for event in trace["events"]
                                if event["kind"] == "task.started" and event["payload"].get("adapter") in {"claude-code", "codex", "opencode"}}
                for task in trace["tasks"]:
                    if task["id"] in native_tasks and task["state"] not in {"verified_complete", "verification_unavailable", "failed"}:
                        label = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode"}[native_tasks[task["id"]]]
                        raise RuntimeError(f"An active {label} task owns this project. End that session or use a separate worktree; do not run the protocol server alongside native supervision.")
                for task in trace["tasks"]:
                    if task["state"] not in {"awaiting_tools", "verified_complete", "verification_unavailable", "failed"}:
                        store.event(task["id"], "recover", "failure", {"class": "tool-error", "context": "Runtime restarted during an active turn; worktree and checkpoints retained for inspection"}, state="failed")
                yield
            finally:
                await upstream.close()
                store.close()
                fcntl.flock(lock, fcntl.LOCK_UN)

    app = FastAPI(title="Aletheia Runtime", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.runtime = runtime

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if token:
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            # Anthropic SDK uses x-api-key rather than Bearer.
            supplied = request.headers.get("x-api-key", supplied)
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return JSONResponse({"error": {"type": "authentication_error", "message": "Local runtime token required"}}, status_code=401)
        elif request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"error": {"type": "permission_error", "message": "Non-loopback hosts require ALETHEIA_LOCAL_TOKEN"}}, status_code=403)
        if request.headers.get("origin"):
            return JSONResponse({"error": {"type": "permission_error", "message": "Browser-origin requests are not supported in v0.1"}}, status_code=403)
        return await call_next(request)

    @app.exception_handler(SupervisionError)
    async def supervision_error(request, exc):
        headers = {"X-Aletheia-Verified": "false"}
        if exc.task_id:
            headers["X-Aletheia-Task"] = exc.task_id
            try:
                headers["X-Aletheia-State"] = store.task(exc.task_id)["state"]
            except KeyError:
                # Unknown tasks are valid 404 errors, not failures of the handler.
                pass
        return JSONResponse({"type": "error", "error": {"type": "supervision_error", "message": str(exc), "task_id": exc.task_id}},
                            status_code=exc.status, headers=headers)

    @app.exception_handler(ToolError)
    async def tool_error(request, exc):
        return JSONResponse({"error": {"type": "invalid_request_error", "message": str(exc)}}, status_code=422)

    @app.get("/v1/models")
    async def models():
        try:
            return await upstream.models()
        except ProviderError as exc:
            return JSONResponse({"error": {"type": "provider_error", "message": str(exc)}}, status_code=502)

    async def supervise(request: Request, protocol: str):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 2_000_000:
                raise SupervisionError("Request exceeds 2 MB", status=413)
        try:
            body = json.loads(data)
        except (ValueError, UnicodeError):
            raise SupervisionError("Malformed request JSON", status=400)
        if not isinstance(body, dict):
            raise SupervisionError("Request must be a JSON object")
        messages, tools, options = normalize(body, protocol)
        if body["model"] not in {config.model, "aletheia"}:
            raise SupervisionError("Use model 'aletheia' or the configured base model; stronger model selection belongs to the escalation rule")
        managed_value = request.headers.get("X-Aletheia-Execute", "false")
        if managed_value not in {"true", "false"}:
            raise SupervisionError("X-Aletheia-Execute must be true or false")
        result, task = await runtime.run(messages, tools, options, protocol=protocol, managed=managed_value == "true",
                                         task_id=request.headers.get("X-Aletheia-Task"), session_id=request.headers.get("X-Aletheia-Session"))
        headers = {"X-Aletheia-Task": task["id"], "X-Aletheia-Session": task["session_id"], "X-Aletheia-State": task["state"],
                   "X-Aletheia-Verified": "true" if task["state"] == "verified_complete" else "false"}
        if body.get("stream"):
            stream_options = body.get("stream_options") or {}
            return StreamingResponse(stream_events(result, protocol, isinstance(stream_options, dict) and bool(stream_options.get("include_usage"))),
                                     media_type="text/event-stream", headers={**headers, "X-Aletheia-Stream": "buffered-until-validated", "Cache-Control": "no-cache"})
        return JSONResponse(anthropic_response(result) if protocol == "anthropic" else result, headers=headers)

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        return await supervise(request, "openai")

    @app.post("/v1/messages")
    async def messages(request: Request):
        return await supervise(request, "anthropic")

    return app

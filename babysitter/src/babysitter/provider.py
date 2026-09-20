"""Model providers (v0.1: exactly one real provider kind).

- :class:`OpenAICompatProvider` — the ONE working provider: any
  OpenAI-compatible ``/chat/completions`` endpoint (free tier, local
  Ollama, ...). One endpoint, possibly several model IDs on it (the
  escalation ladder) — that is one provider, not several.
- :class:`ScriptedProvider` — a deterministic test double. Plays a fixed
  script of turns, records everything it was asked. This is what makes
  the demo and the loop tests reproducible with zero network. A test
  double is not a second provider.

History entries use OpenAI chat shapes throughout Babysitter internals;
the Anthropic protocol adapter translates at the boundary (server.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx


@dataclass
class ToolCall:
    call_id: str
    name: str
    args_raw: str  # exactly what the model emitted (often broken)


@dataclass
class ModelTurn:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class ProviderError(RuntimeError):
    pass


class Provider:
    id: str = "provider"

    def complete(
        self, messages: list[dict], tools: list[dict]
    ) -> ModelTurn:  # pragma: no cover - interface
        raise NotImplementedError


class OpenAICompatProvider(Provider):
    """POSTs to ``{base_url}/chat/completions`` with OpenAI tool schemas."""

    def __init__(
        self,
        model_id: str,
        base_url: str,
        api_key: str = "",
        timeout_s: int = 120,
        client: httpx.Client | None = None,
    ) -> None:
        self.id = model_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        url = self.base_url + "/chat/completions"
        body = {
            "model": self.id,
            "messages": messages,
            "tools": tools or None,
            "tool_choice": "auto" if tools else None,
        }
        body = {k: v for k, v in body.items() if v is not None}
        try:
            if self._client is not None:
                resp = self._client.post(url, json=body, headers=self._headers())
            else:
                with httpx.Client(timeout=self.timeout_s) as client:
                    resp = client.post(url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"provider returned HTTP {resp.status_code}: {resp.text[:500]}"
            )
        try:
            data = resp.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"provider returned bad JSON: {exc}") from exc
        turn = ModelTurn(content=message.get("content") or "")
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {})
            args = fn.get("arguments", "")
            turn.tool_calls.append(
                ToolCall(
                    call_id=call.get("id", ""),
                    name=fn.get("name", ""),
                    args_raw=args if isinstance(args, str) else json.dumps(args),
                )
            )
        return turn

    def check(self) -> str:
        """Lightweight reachability probe for ``babysitter doctor``."""
        url = self.base_url + "/models"
        try:
            if self._client is not None:
                resp = self._client.get(url, headers=self._headers())
            else:
                with httpx.Client(timeout=10) as client:
                    resp = client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            return f"unreachable: {exc}"
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}: {resp.text[:200]}"
        return "ok"


class ScriptedProvider(Provider):
    """Deterministic script of turns. ``script`` items are ModelTurns or
    callables ``(messages, tools, call_index) -> ModelTurn``. When the
    script runs out, the last turn repeats (so runaway loops are the
    loop's bug to catch via max_steps, visibly)."""

    def __init__(self, model_id: str, script: list) -> None:
        if not script:
            raise ValueError("scripted provider needs at least one turn")
        self.id = model_id
        self.script = list(script)
        self.calls: list[dict] = []  # recorded {messages, tools} per call
        self._index = 0

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        item = self.script[min(self._index, len(self.script) - 1)]
        self._index += 1
        if callable(item):
            return item(messages, tools, self._index - 1)
        return item

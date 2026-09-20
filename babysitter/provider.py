"""One provider: an official/local OpenAI-compatible HTTP endpoint."""
from __future__ import annotations

import os

import httpx

from .config import Config


class ProviderError(RuntimeError):
    pass


class OpenAIProvider:
    def __init__(self, config: Config):
        self.config = config
        key = os.environ.get(config.api_key_env)
        self.client = httpx.AsyncClient(base_url=config.provider_url.rstrip("/") + "/",
                                       headers={"Authorization": f"Bearer {key}"} if key else {},
                                       timeout=config.provider_timeout, trust_env=False)

    async def complete(self, messages: list[dict], tools: list[dict], model: str, options: dict) -> dict:
        body = {**options, "model": model, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools
        try:
            response = await self.client.post("chat/completions", json=body)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]:
                raise ValueError("missing choices")
            choice = result["choices"][0]
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                raise ValueError("missing assistant message")
            message = choice["message"]
            if message.get("role") != "assistant" or not isinstance(message.get("content", ""), (str, type(None))):
                raise ValueError("invalid assistant message")
            calls = message.get("tool_calls") or []
            if not isinstance(calls, list) or len(calls) > 32 or any(not isinstance(c, dict) or not isinstance(c.get("function"), dict) for c in calls):
                raise ValueError("invalid or oversized tool batch")
            if not calls and not isinstance(message.get("content"), str):
                raise ValueError("empty assistant message")
            if choice.get("finish_reason") not in {"stop", "tool_calls", "length"}:
                raise ValueError("unsupported/content-filtered provider finish reason")
            return result
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            # Don't expose provider bodies/URLs which may contain secrets.
            raise ProviderError(f"OpenAI-compatible request failed ({type(exc).__name__})") from exc

    async def models(self) -> dict:
        try:
            response = await self.client.get("models")
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise ValueError("missing models data")
            return result
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError(f"Model listing failed ({type(exc).__name__})") from exc

    async def close(self) -> None:
        await self.client.aclose()

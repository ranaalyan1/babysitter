"""Text/function-tool subset; buffered SSE never leaks unvalidated deltas."""
from __future__ import annotations

import json
import time

from .runtime import SupervisionError
from .state import uid


def text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(x, dict) and x.get("type") == "text" and isinstance(x.get("text"), str) for x in content):
        return "\n".join(x["text"] for x in content)
    raise SupervisionError("v0.1 supports text and function tools only; images/audio/thinking are not silently dropped")


def normalize(body: dict, protocol: str) -> tuple[list[dict], list[dict], dict]:
    if not isinstance(body.get("model"), str) or not body["model"]:
        raise SupervisionError("model must be a nonempty string")
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise SupervisionError("messages must be a nonempty array")
    if not isinstance(body.get("stream", False), bool):
        raise SupervisionError("stream must be boolean")
    allowed = {"model", "messages", "tools", "stream", "temperature", "top_p", "max_tokens", "tool_choice", "stop", "n", "stream_options"} if protocol == "openai" else {
        "model", "messages", "tools", "stream", "temperature", "top_p", "max_tokens", "tool_choice", "system", "stop_sequences", "metadata"}
    if body.keys() - allowed:
        raise SupervisionError("Unsupported v0.1 fields: " + ", ".join(sorted(body.keys() - allowed)))
    if body.get("n", 1) != 1:
        raise SupervisionError("v0.1 requires n=1; best-of-N is out of scope")
    for key in ("temperature", "top_p"):
        if key in body and (not isinstance(body[key], (int, float)) or isinstance(body[key], bool)):
            raise SupervisionError(f"{key} must be numeric")
    if "max_tokens" in body and (type(body["max_tokens"]) is not int or body["max_tokens"] <= 0):
        raise SupervisionError("max_tokens must be a positive integer")
    if protocol == "anthropic" and "max_tokens" not in body:
        raise SupervisionError("Anthropic Messages requires max_tokens")
    options = {key: body[key] for key in ("temperature", "top_p", "max_tokens", "tool_choice") if key in body}
    tools = body.get("tools", [])
    if not isinstance(tools, list) or any(not isinstance(x, dict) for x in tools):
        raise SupervisionError("tools must be an array of declarations")
    messages = []
    if protocol == "openai":
        if "stop" in body:
            options["stop"] = body["stop"]
        for item in body["messages"]:
            if not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant", "tool"}:
                raise SupervisionError("invalid OpenAI message role")
            role = item["role"]
            message = {"role": role, "content": text_content(item["content"]) if item.get("content") is not None else None}
            if role == "tool":
                if not isinstance(item.get("tool_call_id"), str):
                    raise SupervisionError("tool result needs tool_call_id")
                message["tool_call_id"] = item["tool_call_id"]
            if "tool_calls" in item:
                if role != "assistant" or not isinstance(item["tool_calls"], list):
                    raise SupervisionError("tool_calls must be an assistant array")
                message["tool_calls"] = item["tool_calls"]
            if message["content"] is None and not message.get("tool_calls"):
                raise SupervisionError("message requires text or tool_calls")
            messages.append(message)
        return messages, tools, options
    if "system" in body:
        messages.append({"role": "system", "content": text_content(body["system"])})
    translated_tools = []
    for tool in tools:
        if not isinstance(tool.get("name"), str) or "input_schema" not in tool:
            raise SupervisionError("Anthropic tool requires name and input_schema")
        translated_tools.append({"type": "function", "function": {"name": tool["name"], "description": tool.get("description", ""),
                                                                  "parameters": tool["input_schema"]}})
    if "stop_sequences" in body:
        options["stop"] = body["stop_sequences"]
    if "tool_choice" in options:
        choice = options["tool_choice"]
        if not isinstance(choice, dict) or choice.get("type") not in {"auto", "any", "none", "tool"}:
            raise SupervisionError("invalid Anthropic tool_choice")
        options["tool_choice"] = ({"type": "function", "function": {"name": choice.get("name")}} if choice["type"] == "tool"
                                  else {"any": "required", "auto": "auto", "none": "none"}[choice["type"]])
    for item in body["messages"]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            raise SupervisionError("invalid Anthropic message role")
        role, content = item["role"], item.get("content")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            raise SupervisionError("message content must be text or blocks")
        texts, calls, results = [], [], []
        for block in content:
            if not isinstance(block, dict):
                raise SupervisionError("invalid content block")
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
            elif kind == "tool_use" and role == "assistant":
                if not isinstance(block.get("id"), str) or not isinstance(block.get("name"), str) or not isinstance(block.get("input"), dict):
                    raise SupervisionError("invalid tool_use block")
                calls.append({"id": block["id"], "type": "function", "function": {"name": block["name"], "arguments": json.dumps(block["input"])}})
            elif kind == "tool_result" and role == "user":
                if not isinstance(block.get("tool_use_id"), str):
                    raise SupervisionError("tool_result needs tool_use_id")
                results.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": text_content(block.get("content", "")),
                                "_is_error": bool(block.get("is_error", False))})
            else:
                raise SupervisionError(f"Unsupported content block: {kind}")
        messages.extend(results)
        if texts or calls:
            messages.append({"role": role, "content": "\n".join(texts) or None, **({"tool_calls": calls} if calls else {})})
    return messages, translated_tools, options


def anthropic_response(response: dict) -> dict:
    message = response["choices"][0]["message"]
    blocks = []
    if message.get("content"):
        blocks.append({"type": "text", "text": message["content"]})
    for call in message.get("tool_calls", []):
        blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": json.loads(call["function"]["arguments"])})
    usage = response.get("usage", {})
    return {"id": "msg_" + uid(), "type": "message", "role": "assistant", "model": response.get("model", "aletheia"),
            "content": blocks, "stop_reason": "tool_use" if message.get("tool_calls") else "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)}}


def stream_events(response: dict, protocol: str, include_usage: bool = False):
    def sse(data, event=None):
        return (("event: " + event + "\n") if event else "") + "data: " + json.dumps(data) + "\n\n"
    if protocol == "openai":
        base = {"id": response.get("id", "chatcmpl-" + uid()), "object": "chat.completion.chunk",
                "created": response.get("created", int(time.time())), "model": response.get("model", "aletheia")}
        message = response["choices"][0]["message"]
        yield sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
        if message.get("content"):
            yield sse({**base, "choices": [{"index": 0, "delta": {"content": message["content"]}, "finish_reason": None}]})
        for index, call in enumerate(message.get("tool_calls", [])):
            yield sse({**base, "choices": [{"index": 0, "delta": {"tool_calls": [{"index": index, **call}]}, "finish_reason": None}]})
        yield sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}]})
        if include_usage:
            yield sse({**base, "choices": [], "usage": response.get("usage", {})})
        yield "data: [DONE]\n\n"
        return
    message = anthropic_response(response)
    yield sse({"type": "message_start", "message": {**message, "content": [], "stop_reason": None,
              "usage": {**message["usage"], "output_tokens": 0}}}, "message_start")
    for index, block in enumerate(message["content"]):
        empty = {**block, **({"text": ""} if block["type"] == "text" else {"input": {}})}
        yield sse({"type": "content_block_start", "index": index, "content_block": empty}, "content_block_start")
        delta = {"type": "text_delta", "text": block["text"]} if block["type"] == "text" else {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        yield sse({"type": "content_block_delta", "index": index, "delta": delta}, "content_block_delta")
        yield sse({"type": "content_block_stop", "index": index}, "content_block_stop")
    yield sse({"type": "message_delta", "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
               "usage": {"output_tokens": message["usage"]["output_tokens"]}}, "message_delta")
    yield sse({"type": "message_stop"}, "message_stop")

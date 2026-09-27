"""OpenAI Responses API adapter for the course's content-block agent loop.

The lessons intentionally use a small content-block protocol (``text``,
``tool_use``, and ``tool_result``).  This module keeps that teaching surface
stable while sending every model request through the official OpenAI SDK.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from openai import OpenAI


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class OpenAIRawBlock:
    """An OpenAI item that must be replayed, such as a reasoning item."""

    raw: Any
    type: str = "openai_raw"


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _block_type(block: Any) -> str | None:
    return _value(block, "type")


def _system_text(system: Any) -> str | None:
    if system is None or isinstance(system, str):
        return system
    parts = []
    for block in system:
        text = _value(block, "text")
        if text:
            parts.append(str(text))
    return "\n\n".join(parts) or None


def _flush_message(items: list[Any], role: str, text_parts: list[str]) -> None:
    if text_parts:
        items.append({"role": role, "content": "\n".join(text_parts)})
        text_parts.clear()


def _response_input(messages: list[dict[str, Any]]) -> list[Any]:
    items: list[Any] = []
    for message in messages:
        role = message["role"]
        content = message.get("content", "")
        if isinstance(content, str):
            items.append({"role": role, "content": content})
            continue

        text_parts: list[str] = []
        for block in content:
            kind = _block_type(block)
            if kind == "text":
                text_parts.append(str(_value(block, "text", "")))
            elif kind == "openai_raw":
                _flush_message(items, role, text_parts)
                items.append(_value(block, "raw"))
            elif kind == "tool_use":
                _flush_message(items, role, text_parts)
                items.append({
                    "type": "function_call",
                    "call_id": str(_value(block, "id")),
                    "name": str(_value(block, "name")),
                    "arguments": json.dumps(
                        _value(block, "input", {}), ensure_ascii=False
                    ),
                })
            elif kind == "tool_result":
                _flush_message(items, role, text_parts)
                output = _value(block, "content", "")
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False)
                if _value(block, "is_error", False):
                    output = f"Error: {output}"
                items.append({
                    "type": "function_call_output",
                    "call_id": str(_value(block, "tool_use_id")),
                    "output": output,
                })
            else:
                text_parts.append(str(block))
        _flush_message(items, role, text_parts)
    return items


def _response_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object"}),
        }
        for tool in (tools or [])
    ]


def _usage(response: Any) -> SimpleNamespace:
    usage = _value(response, "usage")
    input_tokens = int(_value(usage, "input_tokens", 0) or 0)
    output_tokens = int(_value(usage, "output_tokens", 0) or 0)
    details = _value(usage, "input_tokens_details")
    cached_tokens = int(_value(details, "cached_tokens", 0) or 0)
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cached_tokens,
        cache_creation_input_tokens=0,
    )


def _content_blocks(response: Any) -> list[Any]:
    blocks: list[Any] = []
    for item in _value(response, "output", []) or []:
        kind = _block_type(item)
        if kind == "reasoning":
            blocks.append(OpenAIRawBlock(item))
        elif kind == "message":
            for part in _value(item, "content", []) or []:
                part_type = _block_type(part)
                if part_type == "output_text":
                    blocks.append(TextBlock(str(_value(part, "text", ""))))
                elif part_type == "refusal":
                    blocks.append(TextBlock(str(_value(part, "refusal", ""))))
        elif kind == "function_call":
            arguments = _value(item, "arguments", "{}") or "{}"
            try:
                parsed = json.loads(arguments)
            except (TypeError, json.JSONDecodeError):
                parsed = {"_raw": str(arguments)}
            blocks.append(ToolUseBlock(
                id=str(_value(item, "call_id")),
                name=str(_value(item, "name")),
                input=parsed,
            ))
    return blocks


class _Messages:
    def __init__(self, owner: "OpenAICompat") -> None:
        self._owner = owner

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        system: Any = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SimpleNamespace:
        request: dict[str, Any] = {
            "model": model,
            "input": _response_input(messages),
            "max_output_tokens": max_tokens,
        }
        instructions = _system_text(system)
        if instructions:
            request["instructions"] = instructions
        converted_tools = _response_tools(tools)
        if converted_tools:
            request["tools"] = converted_tools
        for option in ("temperature", "top_p"):
            if option in kwargs:
                request[option] = kwargs[option]

        response = self._owner._get_client().responses.create(**request)
        content = _content_blocks(response)
        has_tool_call = any(block.type == "tool_use" for block in content)
        incomplete = _value(response, "incomplete_details")
        incomplete_reason = _value(incomplete, "reason")
        if has_tool_call:
            stop_reason = "tool_use"
        elif incomplete_reason == "max_output_tokens":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"
        return SimpleNamespace(
            content=content,
            stop_reason=stop_reason,
            usage=_usage(response),
            id=_value(response, "id"),
        )


class OpenAICompat:
    """Expose the lesson's ``client.messages.create`` API over OpenAI."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client
        self.messages = _Messages(self)

    def _get_client(self) -> Any:
        if self._client is None:
            options: dict[str, Any] = {
                "api_key": self._api_key or os.getenv("OPENAI_API_KEY")
            }
            if self._base_url:
                options["base_url"] = self._base_url
            self._client = OpenAI(**options)
        return self._client

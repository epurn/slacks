"""Anthropic provider adapter.

Anthropic produces structured output via tool calling: the request declares a
single tool whose ``input_schema`` is the requested JSON Schema and forces the
model to call it, so the tool input is the structured object. The tool input is
returned as a ``dict`` for the base class to validate; it is never trusted or
logged before validation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.llm import transport
from app.llm.base import Provider, build_user_messages, json_schema_for
from app.llm.errors import LLMResponseError

#: Anthropic requires an explicit output bound; a documented tunable.
DEFAULT_MAX_TOKENS = 1024

#: Pinned Messages API version (Anthropic requires this header).
ANTHROPIC_VERSION = "2023-06-01"

#: Name of the single forced tool used to carry structured output.
_TOOL_NAME = "emit_structured_output"


class AnthropicProvider(Provider):
    """Adapter for the Anthropic Messages API (structured output via a tool)."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, max_retries=max_retries)
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens

    def _complete(
        self, prompt: str, schema: type[BaseModel], *, timeout_seconds: float
    ) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": build_user_messages(prompt),
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": "Return the requested structured result.",
                    "input_schema": json_schema_for(schema),
                }
            ],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
        }
        response = transport.post_json(
            f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        return _extract_tool_input(response)


def _extract_tool_input(response: dict[str, Any]) -> dict[str, Any]:
    """Pull the forced tool's input object out of an Anthropic messages response."""

    blocks = response.get("content")
    if not isinstance(blocks, list):
        raise LLMResponseError("provider response missing content blocks") from None
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                raise LLMResponseError("provider tool_use input was not an object") from None
            return tool_input
    raise LLMResponseError("provider response contained no tool_use block") from None

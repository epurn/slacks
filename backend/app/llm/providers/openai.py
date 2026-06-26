"""OpenAI / OpenAI-compatible provider adapter.

Uses the Chat Completions API with ``response_format`` JSON-schema structured
output, so the provider is asked to emit JSON matching the requested schema.
The same wire format serves any OpenAI-compatible endpoint (vLLM, LM Studio,
Together, ...); only the configured base URL differs.

The raw model content is JSON-parsed here and returned as a ``dict``; the base
class validates it against the Pydantic schema. The content is never trusted or
logged before validation.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.llm import transport
from app.llm.base import Provider, build_user_messages, json_schema_for
from app.llm.errors import LLMResponseError


class OpenAIProvider(Provider):
    """Adapter for OpenAI and OpenAI-compatible Chat Completions endpoints."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, max_retries=max_retries)
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    def _complete(
        self, prompt: str, schema: type[BaseModel], *, timeout_seconds: float
    ) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "messages": build_user_messages(prompt),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema_for(schema),
                    "strict": True,
                },
            },
        }
        response = transport.post_json(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        return _extract_content(response)


def _extract_content(response: dict[str, Any]) -> dict[str, Any]:
    """Pull the JSON object out of an OpenAI chat completion response."""

    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMResponseError("provider response missing message content") from None
    if not isinstance(content, str):
        raise LLMResponseError("provider message content was not a string") from None
    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError:
        raise LLMResponseError("provider message content was not valid JSON") from None
    if not isinstance(parsed, dict):
        raise LLMResponseError("provider message content was not a JSON object") from None
    return parsed

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

import base64
import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel

from app.llm import transport
from app.llm.base import ImageInput, Provider, build_user_messages, json_schema_for
from app.llm.errors import LLMResponseError


class OpenAIProvider(Provider):
    """Adapter for OpenAI and OpenAI-compatible Chat Completions endpoints."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        supports_vision: bool = False,
        provider_id: str = "openai",
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            supports_vision=supports_vision,
            model=model,
        )
        # One adapter serves two configured selectors (``openai`` and
        # ``openai_compatible``); the recorded identity must reflect the
        # operator's actual configuration, not the shared wire format, so an
        # estimator audit can tell first-party OpenAI from an OpenRouter/local
        # compatible endpoint (FTY-255).
        self.name = provider_id
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        image_parts = [_image_content_part(image) for image in images or ()]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": build_user_messages(prompt, image_parts),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema_for(schema),
                    "strict": True,
                },
            },
        }
        if _is_openrouter_base_url(self._base_url):
            payload["provider"] = {"require_parameters": True}

        # When no key is configured (keyless local endpoint), omit the header
        # entirely — never send "Bearer " with an empty value.
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = transport.post_json(
            f"{self._base_url}/chat/completions",
            headers=headers,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        return _extract_content(response)


def _is_openrouter_base_url(base_url: str) -> bool:
    """Return whether ``base_url`` is the OpenRouter OpenAI-compatible API root."""

    parsed = urlsplit(base_url.rstrip("/"))
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == "openrouter.ai"
        and parsed.path.rstrip("/") == "/api/v1"
        and not parsed.query
        and not parsed.fragment
    )


def _image_content_part(image: ImageInput) -> dict[str, Any]:
    """Encode an image as an OpenAI ``image_url`` content part (data URL).

    OpenAI carries inline images as a ``data:`` URL inside an ``image_url``
    part; the bytes are base64-encoded here at the wire edge and never logged.
    """

    encoded = base64.b64encode(image.data).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{image.media_type};base64,{encoded}"},
    }


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

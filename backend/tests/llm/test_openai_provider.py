"""OpenAI adapter tests: request construction and response parsing.

The transport is monkeypatched, so these never make a network call. They prove
the adapter builds a correct Chat Completions request and parses (then the base
class validates) the structured content — and that the key and prompt never
reach the logs.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import pytest

from app.llm import transport
from app.llm.errors import LLMResponseError, LLMTransientError
from app.llm.providers.openai import OpenAIProvider
from tests.llm.conftest import (
    SENSITIVE_IMAGE_BYTES,
    Candidate,
    openai_completion,
    sample_image,
)


def _provider(*, supports_vision: bool = False) -> OpenAIProvider:
    return OpenAIProvider(
        api_key="sk-secret-key",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1/",
        timeout_seconds=5.0,
        max_retries=0,
        supports_vision=supports_vision,
    )


def test_builds_request_and_parses_content(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post_json(
        url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        captured["timeout"] = timeout_seconds
        return openai_completion(json.dumps({"name": "apple", "calories": 95}))

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    result = _provider().structured_completion("an apple", Candidate)

    assert result == Candidate(name="apple", calories=95)
    # Trailing slash on base_url is normalized, not doubled.
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-secret-key"
    assert captured["timeout"] == 5.0
    assert captured["payload"]["model"] == "gpt-4o-mini"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "an apple"}]
    response_format = captured["payload"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "Candidate"
    # The JSON Schema sent to the provider is derived from the Pydantic model.
    assert response_format["json_schema"]["schema"] == Candidate.model_json_schema()


def test_image_is_sent_as_a_data_url_content_part(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post_json(
        url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        captured["payload"] = payload
        return openai_completion(json.dumps({"name": "granola bar", "calories": 190}))

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    result = _provider(supports_vision=True).structured_completion(
        "extract the facts", Candidate, images=[sample_image()]
    )

    assert result == Candidate(name="granola bar", calories=190)
    content = captured["payload"]["messages"][0]["content"]
    # The prompt is the leading text part; the image follows as an image_url part.
    assert content[0] == {"type": "text", "text": "extract the facts"}
    encoded = base64.b64encode(SENSITIVE_IMAGE_BYTES).decode("ascii")
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }


def test_non_json_content_is_a_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post_json(url: str, **_: Any) -> dict[str, Any]:
        return openai_completion("not json at all")

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    with pytest.raises(LLMResponseError):
        _provider().structured_completion("an apple", Candidate)


def test_missing_choices_is_a_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post_json(url: str, **_: Any) -> dict[str, Any]:
        return {"choices": []}

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    with pytest.raises(LLMResponseError):
        _provider().structured_completion("an apple", Candidate)


def test_key_and_prompt_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_post_json(url: str, **_: Any) -> dict[str, Any]:
        return openai_completion(json.dumps({"name": "apple", "calories": 95}))

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    with caplog.at_level(logging.INFO, logger="app.llm"):
        _provider().structured_completion("user ate SENSITIVE_FOOD", Candidate)

    assert "sk-secret-key" not in caplog.text
    assert "SENSITIVE_FOOD" not in caplog.text


# ---------------------------------------------------------------------------
# FTY-089: Keyless openai_compatible path
# ---------------------------------------------------------------------------


def _keyless_provider() -> OpenAIProvider:
    return OpenAIProvider(
        api_key=None,
        model="llama3",
        base_url="http://localhost:11434/v1",
        timeout_seconds=5.0,
        max_retries=0,
    )


def test_keyless_sends_no_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    # A keyless adapter must not emit an Authorization header — not even
    # "Bearer " with an empty value.
    captured: dict[str, Any] = {}

    def fake_post_json(
        url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        captured["headers"] = headers
        return openai_completion(json.dumps({"name": "apple", "calories": 95}))

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    _keyless_provider().structured_completion("an apple", Candidate)

    assert "Authorization" not in captured["headers"]


def test_keyed_openai_compatible_sends_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression guard: a keyed openai_compatible adapter still sends Bearer <key>.
    captured: dict[str, Any] = {}

    def fake_post_json(
        url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        captured["headers"] = headers
        return openai_completion(json.dumps({"name": "apple", "calories": 95}))

    monkeypatch.setattr(transport, "post_json", fake_post_json)

    OpenAIProvider(
        api_key="sk-keyed-compat",
        model="llama3",
        base_url="http://localhost:11434/v1",
        timeout_seconds=5.0,
        max_retries=0,
    ).structured_completion("an apple", Candidate)

    assert captured["headers"]["Authorization"] == "Bearer sk-keyed-compat"


def test_transient_error_logging_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_post_json(url: str, **_: Any) -> dict[str, Any]:
        raise LLMTransientError("provider request failed")

    monkeypatch.setattr(transport, "post_json", fake_post_json)
    provider = OpenAIProvider(
        api_key="sk-secret-key",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        timeout_seconds=5.0,
        max_retries=1,
    )

    with caplog.at_level(logging.INFO, logger="app.llm"):
        with pytest.raises(LLMTransientError):
            provider.structured_completion("user ate SENSITIVE_FOOD", Candidate)

    assert "sk-secret-key" not in caplog.text
    assert "SENSITIVE_FOOD" not in caplog.text

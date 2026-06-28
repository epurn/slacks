"""End-to-end ``structured_completion`` flow tests driven by the fake provider.

These cover the acceptance criteria that do not require a live model: schema
validation of trusted output, rejection of schema-invalid output, bounded
retries, and that prompts are never written to logs.
"""

from __future__ import annotations

import logging

import pytest

from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.llm.providers.fake import FakeProvider
from tests.llm.conftest import Candidate


def test_returns_validated_model() -> None:
    provider = FakeProvider(responses=[{"name": "apple", "calories": 95}])

    result = provider.structured_completion("an apple", Candidate)

    assert isinstance(result, Candidate)
    assert result.name == "apple"
    assert result.calories == 95
    assert provider.prompts == ["an apple"]


def test_schema_invalid_output_is_rejected() -> None:
    # "calories" is the wrong type; validation must fail closed, not coerce-and-trust.
    provider = FakeProvider(responses=[{"name": "apple", "calories": "lots"}])

    with pytest.raises(StructuredOutputValidationError):
        provider.structured_completion("an apple", Candidate)


def test_missing_field_output_is_rejected() -> None:
    provider = FakeProvider(responses=[{"name": "apple"}])

    with pytest.raises(StructuredOutputValidationError):
        provider.structured_completion("an apple", Candidate)


def test_retries_then_succeeds_within_bound() -> None:
    provider = FakeProvider(
        responses=[
            LLMTransientError("boom"),
            LLMTransientError("boom"),
            {"name": "apple", "calories": 95},
        ],
        max_retries=2,
        sleep=lambda _: None,
    )

    result = provider.structured_completion("an apple", Candidate)

    assert result.calories == 95
    # 1 initial attempt + 2 retries == 3 calls.
    assert len(provider.prompts) == 3


def test_retries_are_bounded_and_then_raise() -> None:
    provider = FakeProvider(
        responses=[LLMTransientError("boom"), LLMTransientError("boom")],
        max_retries=1,
        sleep=lambda _: None,
    )

    with pytest.raises(LLMTransientError):
        provider.structured_completion("an apple", Candidate)

    # max_retries=1 means exactly 2 attempts before giving up.
    assert len(provider.prompts) == 2


def test_no_scripted_response_raises_configuration_error() -> None:
    provider = FakeProvider()

    with pytest.raises(LLMConfigurationError):
        provider.structured_completion("an apple", Candidate)


def test_prompt_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Redaction: the prompt carries personal context and must not reach logs.
    personal_prompt = "user ate SENSITIVE_BURRITO at midnight"
    provider = FakeProvider(responses=[{"name": "burrito", "calories": 600}])

    with caplog.at_level(logging.INFO, logger="app.llm"):
        provider.structured_completion(personal_prompt, Candidate)

    assert "SENSITIVE_BURRITO" not in caplog.text
    # The success log is still emitted (sanitized), proving logging ran.
    assert "llm call succeeded" in caplog.text


def test_transient_failures_are_logged_without_prompt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    personal_prompt = "user ate SENSITIVE_BURRITO at midnight"
    provider = FakeProvider(
        responses=[LLMTransientError("boom"), {"name": "burrito", "calories": 600}],
        max_retries=1,
        sleep=lambda _: None,
    )

    with caplog.at_level(logging.INFO, logger="app.llm"):
        provider.structured_completion(personal_prompt, Candidate)

    assert "SENSITIVE_BURRITO" not in caplog.text
    assert "llm call transient failure" in caplog.text


# ---------------------------------------------------------------------------
# Backoff seam tests — no real wall-clock delays.
# ---------------------------------------------------------------------------


def test_happy_path_no_sleep() -> None:
    sleeps: list[float] = []
    provider = FakeProvider(
        responses=[{"name": "apple", "calories": 95}],
        sleep=sleeps.append,
    )

    result = provider.structured_completion("an apple", Candidate)

    assert result.calories == 95
    assert sleeps == []


def test_rate_limit_retries_then_succeeds() -> None:
    """A transient error on attempt 1 followed by success: sleep called once."""
    sleeps: list[float] = []
    provider = FakeProvider(
        responses=[LLMTransientError("rate limited"), {"name": "apple", "calories": 95}],
        max_retries=1,
        sleep=sleeps.append,
    )

    result = provider.structured_completion("an apple", Candidate)

    assert result.calories == 95
    assert len(sleeps) == 1
    assert 0.0 <= sleeps[0] <= 8.0


def test_persistent_rate_limit_fails_closed() -> None:
    """Persistent transient errors exhaust the bound; sleep called between each pair."""
    sleeps: list[float] = []
    provider = FakeProvider(
        responses=[
            LLMTransientError("rate limited"),
            LLMTransientError("rate limited"),
            LLMTransientError("rate limited"),
        ],
        max_retries=2,
        sleep=sleeps.append,
    )

    with pytest.raises(LLMTransientError):
        provider.structured_completion("an apple", Candidate)

    # max_retries=2 → 3 attempts → 2 sleeps (between attempt 1→2 and 2→3, never after 3).
    assert len(sleeps) == 2
    assert all(0.0 <= s <= 8.0 for s in sleeps)


def test_no_trailing_sleep_after_final_attempt() -> None:
    """sleep is not called after the last failed attempt."""
    sleeps: list[float] = []
    provider = FakeProvider(
        responses=[LLMTransientError("boom"), LLMTransientError("boom")],
        max_retries=1,
        sleep=sleeps.append,
    )

    with pytest.raises(LLMTransientError):
        provider.structured_completion("an apple", Candidate)

    # 2 attempts, 1 sleep (between them), 0 after the final failure.
    assert len(sleeps) == 1


def test_non_retryable_error_no_sleep() -> None:
    """A non-retryable LLMResponseError propagates immediately with zero sleeps."""
    sleeps: list[float] = []
    provider = FakeProvider(
        responses=[LLMResponseError("bad request")],
        max_retries=2,
        sleep=sleeps.append,
    )

    with pytest.raises(LLMResponseError):
        provider.structured_completion("an apple", Candidate)

    assert sleeps == []

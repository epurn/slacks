"""Adversarial secret-non-disclosure suite (FTY-073).

Proves the threat-model "Provider key leakage" / "Sensitive data in logs, prompts,
analytics" controls and the ``llm-provider`` contract's privacy clause: provider
keys, prompts, and raw provider responses are never logged and never returned, and
transport errors are content-free.

It extends ``tests/llm/test_structured_completion.py`` and
``tests/test_logging.py`` by asserting, across the *whole* log-record (not just the
formatted message), that neither the prompt nor the raw response — which may carry
echoed personal context — reaches any log record on success, on schema rejection,
or across retries; and that the redaction filter scrubs header/secret-shaped keys.
"""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import BaseModel, SecretStr

from app.estimator.search import SearchSettings
from app.llm.errors import LLMTransientError, StructuredOutputValidationError
from app.llm.providers.fake import FakeProvider
from app.logging import REDACTED, RedactionFilter


class _Candidate(BaseModel):
    name: str
    calories: int


#: A marker we plant in prompts/responses; if it surfaces in a log record, a secret
#: or personal value leaked.
_MARKER = "SENSITIVE_BURRITO_9000"


def _record_blob(record: logging.LogRecord) -> str:
    """Serialize an entire log record (message + every extra field) for scanning."""

    blob = {k: v for k, v in record.__dict__.items()}
    blob["__message__"] = record.getMessage()
    return json.dumps(blob, default=str)


def test_prompt_and_raw_response_absent_from_logs_on_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider(responses=[{"name": _MARKER, "calories": 500}])
    with caplog.at_level(logging.DEBUG, logger="app.llm"):
        result = provider.structured_completion(f"user ate {_MARKER}", _Candidate)

    # The call ran (a success log was emitted) ...
    assert any(r.levelno == logging.INFO for r in caplog.records)
    # ... but neither the prompt nor the (echoed) raw response is anywhere in any
    # log record — only provider/attempt metadata is logged.
    assert result.name == _MARKER  # returned to the caller, never logged
    for record in caplog.records:
        assert _MARKER not in _record_blob(record)


def test_rejected_payload_absent_from_logs(caplog: pytest.LogCaptureFixture) -> None:
    # A schema-invalid reply is untrusted and may echo personal context; the
    # rejection logs only an error count, never the offending payload.
    provider = FakeProvider(responses=[{"name": _MARKER}])  # missing required "calories"
    with caplog.at_level(logging.DEBUG, logger="app.llm"):
        with pytest.raises(StructuredOutputValidationError):
            provider.structured_completion(f"user ate {_MARKER}", _Candidate)

    assert any("rejected" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        assert _MARKER not in _record_blob(record)


def test_prompt_absent_from_logs_across_retries(caplog: pytest.LogCaptureFixture) -> None:
    provider = FakeProvider(
        responses=[
            LLMTransientError("connect to provider failed"),
            {"name": "ok", "calories": 1},
        ],
        max_retries=2,
    )
    with caplog.at_level(logging.DEBUG, logger="app.llm"):
        provider.structured_completion(f"user ate {_MARKER}", _Candidate)

    # Both the transient-failure and success paths logged, neither carrying the prompt.
    assert any("transient" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        assert _MARKER not in _record_blob(record)


@pytest.mark.parametrize(
    "field",
    [
        "api_key",
        "x_api_key",
        "authorization",
        "x_subscription_token",
        "access_key",
        "session_cookie",
        "password",
    ],
)
def test_redaction_filter_scrubs_secret_and_header_shaped_keys(field: str) -> None:
    record = logging.makeLogRecord({"msg": "provider call", field: "super-secret-value"})
    RedactionFilter().filter(record)
    assert getattr(record, field) == REDACTED


def test_non_sensitive_fields_survive_redaction() -> None:
    record = logging.makeLogRecord({"msg": "ok", "provider": "fake", "attempt": 2})
    RedactionFilter().filter(record)
    assert record.provider == "fake"  # type: ignore[attr-defined]
    assert record.attempt == 2  # type: ignore[attr-defined]


def test_search_api_key_is_masked_in_repr_and_str() -> None:
    settings = SearchSettings(api_key=SecretStr("super-secret-key"))
    assert "super-secret-key" not in repr(settings)
    assert "super-secret-key" not in str(settings)
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "super-secret-key"

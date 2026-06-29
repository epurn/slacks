"""Adversarial secret-non-disclosure suite (FTY-073, FTY-139).

Proves the threat-model "Provider key leakage" / "Sensitive data in logs, prompts,
analytics" controls and the ``llm-provider`` contract's privacy clause: provider
keys, prompts, and raw provider responses are never logged and never returned, and
transport errors are content-free.

It extends ``tests/llm/test_structured_completion.py`` and
``tests/test_logging.py`` by asserting, across the *whole* log-record (not just the
formatted message), that neither the prompt nor the raw response — which may carry
echoed personal context — reaches any log record on success, on schema rejection,
or across retries; and that the redaction filter scrubs header/secret-shaped keys.

FTY-139 extends this suite with value-pattern redaction: token-shaped values
(Bearer tokens, JWTs, provider API keys) embedded in formatted messages or
serialised exception traces are also scrubbed.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.estimator.search import SearchSettings
from app.llm.errors import LLMTransientError, StructuredOutputValidationError
from app.llm.providers.fake import FakeProvider
from app.logging import REDACTED, JsonFormatter, RedactionFilter, _redact_values


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


# ---------------------------------------------------------------------------
# FTY-139: value-pattern redaction in messages and exc_info
# ---------------------------------------------------------------------------


def _fmt(msg: str, *args: object) -> Any:
    """Format a log record through JsonFormatter and return the parsed payload."""
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )
    return json.loads(JsonFormatter().format(record))


@pytest.mark.parametrize(
    "secret",
    [
        # Bearer token
        "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123def456",
        # Standalone JWT (not Bearer-prefixed)
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123def456ghi789",
        # OpenAI-style key
        "sk-abcdefghij1234567890klmnopqrstuvwxyzABCD",
        # OpenAI project key (sk-proj-…)
        "sk-proj-abcdefghij1234567890klmnopqrstu",
        # GitHub personal-access token
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890ab",
        # AWS access key ID
        "AKIA1234567890ABCDEF",
    ],
)
def test_token_shaped_value_redacted_in_message(secret: str) -> None:
    payload = _fmt("calling API: %s", secret)
    assert secret not in str(payload["message"])
    assert REDACTED in str(payload["message"])


@pytest.mark.parametrize(
    ("raw", "expected_key_present"),
    [
        ("token=super-secret-value-xyz", "token="),
        ("api_key=super-secret-value-xyz", "api_key="),
        ("password: hunter2-super-secret", "password:"),
    ],
)
def test_inline_key_value_redacts_value_preserves_key(raw: str, expected_key_present: str) -> None:
    result = _redact_values(raw)
    assert REDACTED in result
    # The key name (and separator) is preserved; only the value is replaced.
    assert expected_key_present in result
    # The original secret value is gone.
    assert "super-secret-value-xyz" not in result
    assert "hunter2-super-secret" not in result


def test_bearer_token_label_preserved_after_redaction() -> None:
    # When Bearer appears without a key=value prefix, the "Bearer " label is kept.
    result = _redact_values("calling API: Bearer sk-super-long-secret-key-1234567890")
    assert "Bearer" in result
    assert REDACTED in result
    assert "sk-super-long-secret-key-1234567890" not in result


def test_authorization_header_fully_redacted() -> None:
    # When Authorization: Bearer … appears, the inline key=value arm fires first
    # (Authorization is a sensitive key), so the entire header value is redacted.
    result = _redact_values("Authorization: Bearer sk-super-long-secret-key-1234567890")
    assert REDACTED in result
    assert "sk-super-long-secret-key-1234567890" not in result


def test_exc_info_with_secret_is_redacted() -> None:
    fake_api_key = "sk-leakedsecretkey1234567890abcdefgh"
    try:
        raise RuntimeError(f"provider failure: {fake_api_key}")
    except RuntimeError:
        exc = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider call failed",
        args=(),
        exc_info=exc,
    )
    payload = json.loads(JsonFormatter().format(record))
    exc_text = str(payload.get("exc_info", ""))
    assert fake_api_key not in exc_text
    assert REDACTED in exc_text


@pytest.mark.parametrize(
    "safe_value",
    [
        # UUID with hyphens
        "550e8400-e29b-41d4-a716-446655440000",
        # Request / event ID
        "req_abc123def456",
        # ISO-8601 timestamp
        "2024-01-15T10:30:00Z",
        # File path
        "/home/user/data/fatty/logs/app.log",
        # Ordinary sentence
        "User logged a chicken sandwich for lunch",
        # Bare integer
        "42",
        # Bare float
        "3.14",
        # Email as identifier (non-secret context)
        "evan.purney@gmail.com",
    ],
)
def test_normal_corpus_not_redacted(safe_value: str) -> None:
    """False-positive gate: representative non-secret values pass through unmodified."""
    assert _redact_values(safe_value) == safe_value


def test_field_name_redaction_unchanged_after_value_redaction_added() -> None:
    """Regression: existing field-name redaction still operates correctly."""
    record = logging.makeLogRecord({"msg": "check", "api_key": "still-secret"})
    RedactionFilter().filter(record)
    assert record.api_key == REDACTED  # type: ignore[attr-defined]

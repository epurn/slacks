"""Transport error-mapping tests.

``urllib`` is monkeypatched so no socket is opened. These prove the single error
classification every provider relies on: ``5xx``/timeout/connection -> retryable
transient; ``4xx``/non-JSON -> non-retryable response error; and that disallowed
URL schemes fail closed.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from email.message import Message
from types import TracebackType
from typing import Any

import pytest

from app.estimator.hardened_fetch import DEFAULT_MAX_BYTES
from app.llm import transport
from app.llm.errors import LLMConfigurationError, LLMResponseError, LLMTransientError


class _FakeResponse:
    """Minimal stand-in for the ``urlopen`` context-manager response."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def read(self, n: int = -1) -> bytes:
        # Return the full body regardless of the size hint; the transport checks
        # the returned length itself (mirroring hardened_fetch._open_json).
        return self._body


def _post(url: str = "https://api.example.com/v1/x") -> dict[str, Any]:
    return transport.post_json(
        url, headers={"Authorization": "Bearer k"}, payload={"a": 1}, timeout_seconds=1.0
    )


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(LLMConfigurationError):
        transport.post_json("file:///etc/passwd", headers={}, payload={}, timeout_seconds=1.0)


def test_parses_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b'{"ok": true}'))

    assert _post() == {"ok": True}


def test_http_500_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.HTTPError(
            "https://api.example.com", 503, "busy", Message(), io.BytesIO(b"upstream")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(LLMTransientError):
        _post()


def test_http_401_is_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.HTTPError(
            "https://api.example.com", 401, "denied", Message(), io.BytesIO(b"nope")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(LLMResponseError):
        _post()


def test_http_400_is_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.HTTPError(
            "https://api.example.com", 400, "bad request", Message(), io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(LLMResponseError):
        _post()


def test_http_429_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.HTTPError(
            "https://api.example.com", 429, "too many requests", Message(), io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(LLMTransientError):
        _post()


def test_http_408_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.HTTPError(
            "https://api.example.com", 408, "request timeout", Message(), io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(LLMTransientError):
        _post()


def test_http_425_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.HTTPError(
            "https://api.example.com", 425, "too early", Message(), io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(LLMTransientError):
        _post()


def test_connection_failure_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(LLMTransientError):
        _post()


def test_timeout_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    with pytest.raises(LLMTransientError):
        _post()


def test_non_json_body_is_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b"<html>nope</html>")
    )

    with pytest.raises(LLMResponseError):
        _post()


def test_json_array_body_is_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b"[1, 2, 3]"))

    with pytest.raises(LLMResponseError):
        _post()


# --- Size-cap tests (transport parity with hardened_fetch) ---


def test_over_cap_body_raises_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A body one byte over the cap must raise LLMResponseError without OOM-ing.
    oversized = b"x" * (DEFAULT_MAX_BYTES + 1)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResponse(oversized))

    with pytest.raises(LLMResponseError):
        _post()


def test_over_cap_error_message_contains_no_body(monkeypatch: pytest.MonkeyPatch) -> None:
    # The error message must never include the body (even a snippet of it).
    body_marker = b"BODY_MARKER_MUST_NOT_LEAK"
    oversized = body_marker + b"x" * DEFAULT_MAX_BYTES
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResponse(oversized))

    with pytest.raises(LLMResponseError) as exc_info:
        _post()

    assert body_marker.decode() not in str(exc_info.value)
    assert "BODY_MARKER" not in str(exc_info.value)


def test_at_cap_body_parses_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    # A body exactly at the cap (a valid JSON object) must parse without error.
    prefix = b'{"ok": true, "pad": "'
    suffix = b'"}'
    padding = b"a" * (DEFAULT_MAX_BYTES - len(prefix) - len(suffix))
    padded = prefix + padding + suffix
    assert len(padded) == DEFAULT_MAX_BYTES
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResponse(padded))

    result = _post()
    assert result["ok"] is True


def test_under_cap_body_parses_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    # A normal-sized response must pass through unchanged.
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b'{"ok": true}'))

    assert _post() == {"ok": True}

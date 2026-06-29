"""Structured logging configured to never emit secrets or personal data.

Logs are emitted as single-line JSON so they are machine-parseable, and a
redaction filter scrubs any log record field whose name looks sensitive (tokens,
secrets, keys, passwords, authorization headers, cookies). A second pass scrubs
token-shaped values from rendered messages and serialised exception traces, so a
future careless log line or a third-party exception message cannot print a
credential unredacted. This redaction posture is a security-sensitive convention
later stories inherit: prefer request/event IDs over personal values, and never
attach raw prompts, provider keys, or food history to log records.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

#: Placeholder substituted for the value of any sensitive log field or value.
REDACTED = "[REDACTED]"

#: Field names matching this pattern are redacted before formatting.
_SENSITIVE_KEY = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|access[_-]?key|authorization|auth|cookie|key)",
    re.IGNORECASE,
)

#: Token-shaped values redacted from rendered messages and serialised exc_info.
#: Only specific, low-false-positive shapes are included; the inline key=value
#: arm reuses the _SENSITIVE_KEY vocabulary.  Compiled once at import.
#:
#: Capture groups used by _redact_values:
#:   group 1 — "Bearer " prefix (preserved, credential replaced)
#:   group 2 — "key= " prefix (preserved, value replaced)
#:   no group  — entire match replaced
_SENSITIVE_VALUE = re.compile(
    # Bearer token: keep the label, redact the credential
    r"(Bearer\s+)\S+"
    # JWT: three base64url segments; header always begins eyJ (base64url of '{"')
    r"|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    # OpenAI-style provider keys (sk-… and sk-proj-…)
    r"|sk-[A-Za-z0-9_-]{20,}"
    # Slack bot/app/user/remote/workspace tokens
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    # GitHub personal-access / OAuth / server / refresh tokens
    r"|gh[pousr]_[A-Za-z0-9]{36,}"
    # AWS access key IDs
    r"|AKIA[0-9A-Z]{16}"
    # Inline key=value / key: value where the key name is sensitive;
    # keep the key prefix, redact the value
    r"|((?:secret|token|password|passwd|api[_-]?key|access[_-]?key"
    r"|authorization|auth|cookie|key)\s*[:=]\s*)\S+",
    re.IGNORECASE,
)

#: Standard ``LogRecord`` attributes that are never treated as extra fields.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def _redact_values(text: str) -> str:
    """Replace token-shaped secrets in *text* with the REDACTED sentinel.

    For alternatives that capture a non-secret prefix (Bearer label, key name)
    the prefix is preserved and only the credential portion is replaced.
    """

    def _replace(m: re.Match[str]) -> str:
        prefix = m.group(1) or m.group(2)
        return (prefix + REDACTED) if prefix else REDACTED

    return _SENSITIVE_VALUE.sub(_replace, text)


class RedactionFilter(logging.Filter):
    """Redact sensitive ``extra`` fields in place before they are formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__):
            if key in _RESERVED:
                continue
            if _SENSITIVE_KEY.search(key):
                record.__dict__[key] = REDACTED
        return True


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact_values(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = _redact_values(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Install the JSON formatter and redaction filter on the root logger."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

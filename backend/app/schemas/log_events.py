"""Log-event boundary DTOs (FTY-030, FTY-096).

The create request and the event DTO are contracts consumed by the mobile Today
timeline (FTY-031) and polling (FTY-032). ``raw_text`` is untrusted user input:
it is bounds-checked and required to be non-empty here, the single trust
boundary before it is persisted.

FTY-096 adds an optional ``idempotency_key`` so an offline-queued entry can be
submitted safe-to-retry on reconnect: the key is an opaque client token (a
UUID/ULID by convention — the server never parses it), validated as bounded data
at the same boundary that guards ``raw_text``. It is not echoed in the DTO.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import LogEventStatus

#: Maximum accepted length of a single raw log entry. Generous enough for a
#: natural-language meal/exercise description while capping unbounded input.
MAX_RAW_TEXT_LENGTH = 2000

#: Maximum accepted length of an opaque client idempotency key. A UUID/ULID is
#: well under this; the cap bounds the stored, unparsed token.
MAX_IDEMPOTENCY_KEY_LENGTH = 200


class LogEventCreateRequest(BaseModel):
    """Request body for ``POST /api/users/{user_id}/log-events``.

    ``raw_text`` must be non-empty after trimming and at most
    :data:`MAX_RAW_TEXT_LENGTH` characters; surrounding whitespace is stripped so
    a whitespace-only entry is rejected rather than stored as blank.

    ``idempotency_key`` is optional. When present it is an opaque client token,
    trimmed, non-empty after trimming, and at most
    :data:`MAX_IDEMPOTENCY_KEY_LENGTH` characters; the server stores it verbatim
    and never interprets it. Omitting it preserves the original create behaviour.
    """

    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1, max_length=MAX_RAW_TEXT_LENGTH)
    idempotency_key: str | None = Field(default=None, max_length=MAX_IDEMPOTENCY_KEY_LENGTH)

    @field_validator("raw_text")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("raw_text must not be empty or whitespace only")
        return stripped

    @field_validator("idempotency_key")
    @classmethod
    def _strip_key_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("idempotency_key must not be empty or whitespace only")
        return stripped


class LogEventDTO(BaseModel):
    """Response body for the log-event create/list/get API.

    Built directly from the :class:`~app.models.log_events.LogEvent` ORM row.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    raw_text: str
    status: LogEventStatus
    created_at: datetime
    updated_at: datetime

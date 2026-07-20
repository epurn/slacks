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
from app.schemas.corrections import DerivedExerciseItemDTO, DerivedFoodItemDTO

#: Maximum accepted length of a single raw log entry. Generous enough for a
#: natural-language meal/exercise description while capping unbounded input.
MAX_RAW_TEXT_LENGTH = 2000

#: Maximum accepted length of an opaque client idempotency key. A UUID/ULID is
#: well under this; the cap bounds the stored, unparsed token.
MAX_IDEMPOTENCY_KEY_LENGTH = 200

#: Maximum accepted length of a clarification answer (FTY-170/171). An answer is
#: a short missing detail ("4", "2%", "1 tbsp"); the cap bounds the stored,
#: uninterpreted text.
MAX_ANSWER_LENGTH = 300


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


class LogEventMultipartPayload(BaseModel):
    """The JSON ``payload`` part of a multipart create (FTY-375).

    Field rules match :class:`LogEventCreateRequest` exactly, except ``raw_text``
    is optional: a submission may carry images only, in which case the route
    stores the fixed ``"Photo log"`` marker (``docs/contracts/log-event-images.md``).
    When present, ``raw_text`` is trimmed, non-empty after trimming, and at most
    :data:`MAX_RAW_TEXT_LENGTH` characters. The at-least-one-surface rule (text
    and/or ≥1 image) is enforced at the route, where the image parts are known.

    Validation failures on this part are rendered as a **content-free** ``422``
    (a fixed action description, never the rejected input), because the payload
    carries sensitive log text.
    """

    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = Field(default=None, max_length=MAX_RAW_TEXT_LENGTH)
    idempotency_key: str | None = Field(default=None, max_length=MAX_IDEMPOTENCY_KEY_LENGTH)

    @field_validator("raw_text")
    @classmethod
    def _strip_optional_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
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
    #: Short, model-generated meal label (FTY-421), e.g. ``"Turkey sandwich"``.
    #: Always present in the response shape and ``null`` until the estimator
    #: (FTY-422) names the event — nothing populates it in this story.
    name: str | None = None
    status: LogEventStatus
    created_at: datetime
    updated_at: datetime


class LogEventEntryDTO(BaseModel):
    """Today-feed-shaped day-listing row (FTY-198).

    Carries the owning log event plus the derived food/exercise items the Today
    timeline renders beneath it. Item DTOs reuse the shared correction/item
    read-model, including per-item ``source`` provenance and ``is_edited``.
    """

    event: LogEventDTO
    items: list[DerivedFoodItemDTO | DerivedExerciseItemDTO]


class ClarificationQuestionDTO(BaseModel):
    """A single persisted clarification question (FTY-152, FTY-170/171).

    Carries the stored row's stable ``id`` (the key an answer submission
    references), the question ``text``, and the quick-pick ``options`` the
    clarify sheet renders as one-tap chips. Options are display candidates only —
    never an enum the server validates an answer against; free text is always an
    allowed answer. The list may be empty only for deterministic backend-raised
    questions that have no meaningful quick-pick set; model-raised parse
    clarifications carry producer-generated options (``parse-candidates.md`` v2).
    """

    id: uuid.UUID
    text: str
    options: list[str] = Field(default_factory=list)


class ClarificationResponse(BaseModel):
    """Response body for the owner-scoped clarification read.

    Carries a ``needs_clarification`` or ``partially_resolved`` event's
    **unanswered** clarification questions ordered by ``position``. The read is
    status-gated: an owned event in any other status — or one with no unanswered
    rows — yields an empty list, and the two cases are indistinguishable (no
    status oracle).
    """

    questions: list[ClarificationQuestionDTO]


class ClarificationAnswerRequest(BaseModel):
    """Request body for ``POST .../log-events/{event_id}/clarification/answers``.

    ``question_id`` references one of the event's persisted clarification
    questions (from the clarification read). ``answer`` is the user's answer as
    opaque text — a tapped quick-pick option's value or free text. It is
    untrusted user input validated as bounded **data** at this single trust
    boundary: trimmed, non-empty after trimming (an empty/whitespace answer is
    rejected ``422`` before any work — finding A5), and at most
    :data:`MAX_ANSWER_LENGTH` characters. It is never validated against the
    question's options and never interpreted.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_LENGTH)

    @field_validator("answer")
    @classmethod
    def _strip_answer_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("answer must not be empty or whitespace only")
        return stripped

"""Provider adapter interface and the shared ``structured_completion`` flow.

The provider layer exposes exactly one capability: given a prompt and a schema,
return a schema-validated object. The schema is expressed as a Pydantic model
type — it both carries the JSON Schema sent to the provider's structured-output
mechanism (via :meth:`pydantic.BaseModel.model_json_schema`) and validates the
response. The contract is "schema-validated object out"; the per-provider
structured-output mechanism (JSON mode vs. tool calling) is an implementation
detail (see ``docs/contracts/llm-provider.md``).

The LLM is treated as an untrusted analyst: every response is validated before
it is returned, and validation failures are rejected, never returned as trusted
(see ``docs/security/security-baseline.md``). Every call is bounded by a timeout
and a fixed number of retries, and emits only sanitized log fields — never the
prompt, the key, or the raw response.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.errors import (
    LLMConfigurationError,
    LLMTransientError,
    StructuredOutputValidationError,
)

#: A response schema is any Pydantic model type; the validated instance is returned.
OutputT = TypeVar("OutputT", bound=BaseModel)

#: Media types a vision-capable provider is asked to accept. Kept small and
#: explicit so an unsupported type fails fast at the input boundary rather than
#: at the provider. These are the formats OpenAI and Anthropic both accept.
ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})

logger = logging.getLogger("app.llm")

# Full-jitter exponential backoff constants for transient-error retries.
# base * 2**(attempt-1) seconds, capped at _BACKOFF_CAP, with uniform jitter.
# These are intentionally internal — not promoted to FATTY_LLM_* config.
_BACKOFF_BASE: float = 0.5
_BACKOFF_CAP: float = 8.0


@dataclass(frozen=True)
class ImageInput:
    """One image supplied alongside the prompt for a vision-capable completion.

    The image is *untrusted input* — data, not instructions. As with the prompt,
    nothing about it is ever logged, and any structured output a model derives
    from it is trusted only after it validates against the caller's schema (see
    ``docs/contracts/llm-provider.md`` v2).

    Args:
        data: the raw image bytes. Providers base64-encode these at the wire
            edge; callers pass bytes, not an already-encoded string.
        media_type: the IANA media type, e.g. ``image/jpeg``. Must be one of
            :data:`ALLOWED_IMAGE_MEDIA_TYPES`.
    """

    data: bytes
    media_type: str

    def __post_init__(self) -> None:
        if not self.data:
            raise LLMConfigurationError("image input has no data")
        if self.media_type not in ALLOWED_IMAGE_MEDIA_TYPES:
            # Content-free message: never echo the (untrusted) media type value
            # verbatim into logs/traces; the allowed set is static and public.
            raise LLMConfigurationError("image input has an unsupported media type")


class Provider(ABC):
    """Base class for LLM provider adapters.

    Subclasses implement :meth:`_complete` — a single network round-trip that
    returns the provider's raw structured payload as a ``dict``. This base class
    owns the cross-cutting concerns that every provider must share: bounded
    retries on transient failures, sanitized per-attempt logging, and schema
    validation of the result. Subclasses never log and never validate, so those
    controls cannot be forgotten or implemented inconsistently per provider.
    """

    #: Stable, non-sensitive provider label used in logs.
    name: str = "provider"

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_retries: int,
        supports_vision: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        #: Whether the configured model accepts image input. Declared by config
        #: (``FATTY_LLM_SUPPORTS_VISION``); image input with a non-vision model
        #: fails fast in :meth:`structured_completion` before any provider call.
        self._supports_vision = supports_vision
        # Injectable sleep seam: default is time.sleep in production; tests pass
        # a fake that records delays and returns instantly (no real wall-clock wait).
        self._sleep = sleep

    def structured_completion(
        self,
        prompt: str,
        schema: type[OutputT],
        *,
        images: Sequence[ImageInput] | None = None,
    ) -> OutputT:
        """Return a schema-validated object for ``prompt`` (and optional images).

        Calls the provider with bounded retries, then validates the raw response
        against ``schema``. Schema-invalid output is rejected with
        :class:`StructuredOutputValidationError` and never returned as trusted.

        ``images`` is optional and defaults to ``None`` — the text-only call is
        unchanged. When images are supplied the configured model must be
        vision-capable; otherwise this fails fast with
        :class:`LLMConfigurationError` *before* any provider call, so an image is
        never sent to a model that cannot read it. Images, like the prompt, are
        untrusted input and are never logged.

        Raises:
            LLMConfigurationError: images were supplied but the configured model
                is not vision-capable.
            LLMTransientError: every attempt failed with a transient error.
            LLMResponseError: the provider replied with something unusable.
            StructuredOutputValidationError: the reply failed schema validation.
        """

        if images and not self._supports_vision:
            # Fail closed before any network call: a non-vision model silently
            # ignoring an image would be a worse, late failure mode.
            raise LLMConfigurationError(
                "image input requires a vision-capable configured model "
                "(set FATTY_LLM_SUPPORTS_VISION=true for a vision model)"
            )

        raw = self._complete_with_retries(prompt, schema, images)
        try:
            return schema.model_validate(raw)
        except ValidationError as exc:
            # Log only the error count and provider — never the offending payload,
            # which is untrusted and may carry echoed personal context.
            logger.warning(
                "llm structured output rejected",
                extra={
                    "provider": self.name,
                    "schema": schema.__name__,
                    "error_count": exc.error_count(),
                },
            )
            raise StructuredOutputValidationError(
                f"provider output failed validation against {schema.__name__}"
            ) from None

    def _complete_with_retries(
        self,
        prompt: str,
        schema: type[OutputT],
        images: Sequence[ImageInput] | None,
    ) -> dict[str, Any]:
        """Invoke :meth:`_complete`, retrying transient failures up to the bound."""

        attempts = self._max_retries + 1
        # ``attempts >= 1`` always (``max_retries >= 0``), so the loop runs at
        # least once; the sentinel is only ever replaced by a real failure.
        last_error: LLMTransientError = LLMTransientError("no attempt was made")
        for attempt in range(1, attempts + 1):
            try:
                result = self._complete(
                    prompt, schema, images=images, timeout_seconds=self._timeout_seconds
                )
            except LLMTransientError as exc:
                last_error = exc
                has_next = attempt < attempts
                # Only compute a backoff when there is a next attempt to delay.
                # Never sleep after the final attempt — the caller gets the error
                # immediately, without a trailing wait.
                backoff = (
                    random.uniform(0, min(_BACKOFF_CAP, _BACKOFF_BASE * 2 ** (attempt - 1)))  # noqa: S311
                    if has_next
                    else 0.0
                )
                # Log the failure type and attempt number only; the exception
                # message is deliberately content-free (see errors module).
                # backoff_seconds is a bounded number and safe to log.
                logger.warning(
                    "llm call transient failure",
                    extra={
                        "provider": self.name,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "error_type": type(exc).__name__,
                        "backoff_seconds": backoff,
                    },
                )
                if has_next:
                    self._sleep(backoff)
                continue
            logger.info(
                "llm call succeeded",
                extra={"provider": self.name, "attempt": attempt},
            )
            return result
        raise last_error

    @abstractmethod
    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """Perform one provider round-trip and return the raw structured payload.

        ``images`` is ``None`` for a text-only call; when present the provider
        attaches them using its own multimodal mechanics. Implementations must
        raise :class:`LLMTransientError` for retryable transport failures and
        :class:`LLMResponseError` for unusable replies. They must never log the
        prompt, the images, the key, or the raw response.
        """


def build_user_messages(
    prompt: str, content_parts: Sequence[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Wrap a prompt as a single-turn user message (shared by chat providers).

    With no ``content_parts`` the message is the plain text-only shape, byte-for-
    byte identical to the v1 request. When a provider supplies its own image
    ``content_parts`` (OpenAI image-url parts, Anthropic image blocks), the
    prompt becomes the leading text part and the images follow.
    """

    if not content_parts:
        return [{"role": "user", "content": prompt}]
    return [
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt}, *content_parts],
        }
    ]


def json_schema_for(schema: type[BaseModel]) -> dict[str, Any]:
    """Return the JSON Schema a provider's structured-output API should enforce."""

    return schema.model_json_schema()

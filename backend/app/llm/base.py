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
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.errors import LLMTransientError, StructuredOutputValidationError

#: A response schema is any Pydantic model type; the validated instance is returned.
OutputT = TypeVar("OutputT", bound=BaseModel)

logger = logging.getLogger("app.llm")


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

    def __init__(self, *, timeout_seconds: float, max_retries: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    def structured_completion(self, prompt: str, schema: type[OutputT]) -> OutputT:
        """Return a schema-validated object for ``prompt``.

        Calls the provider with bounded retries, then validates the raw response
        against ``schema``. Schema-invalid output is rejected with
        :class:`StructuredOutputValidationError` and never returned as trusted.

        Raises:
            LLMTransientError: every attempt failed with a transient error.
            LLMResponseError: the provider replied with something unusable.
            StructuredOutputValidationError: the reply failed schema validation.
        """

        raw = self._complete_with_retries(prompt, schema)
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
            ) from exc

    def _complete_with_retries(self, prompt: str, schema: type[OutputT]) -> dict[str, Any]:
        """Invoke :meth:`_complete`, retrying transient failures up to the bound."""

        attempts = self._max_retries + 1
        # ``attempts >= 1`` always (``max_retries >= 0``), so the loop runs at
        # least once; the sentinel is only ever replaced by a real failure.
        last_error: LLMTransientError = LLMTransientError("no attempt was made")
        for attempt in range(1, attempts + 1):
            try:
                result = self._complete(prompt, schema, timeout_seconds=self._timeout_seconds)
            except LLMTransientError as exc:
                # Log the failure *type* and attempt number only; the exception
                # message is deliberately content-free (see errors module).
                last_error = exc
                logger.warning(
                    "llm call transient failure",
                    extra={
                        "provider": self.name,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "error_type": type(exc).__name__,
                    },
                )
                continue
            logger.info(
                "llm call succeeded",
                extra={"provider": self.name, "attempt": attempt},
            )
            return result
        raise last_error

    @abstractmethod
    def _complete(
        self, prompt: str, schema: type[BaseModel], *, timeout_seconds: float
    ) -> dict[str, Any]:
        """Perform one provider round-trip and return the raw structured payload.

        Implementations must raise :class:`LLMTransientError` for retryable
        transport failures and :class:`LLMResponseError` for unusable replies.
        They must never log the prompt, the key, or the raw response.
        """


def build_user_messages(prompt: str) -> list[dict[str, str]]:
    """Wrap a prompt as a single-turn user message (shared by chat providers)."""

    return [{"role": "user", "content": prompt}]


def json_schema_for(schema: type[BaseModel]) -> dict[str, Any]:
    """Return the JSON Schema a provider's structured-output API should enforce."""

    return schema.model_json_schema()

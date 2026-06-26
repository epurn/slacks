"""Error hierarchy for the LLM provider layer.

Errors are deliberately coarse and message-light: a provider call can fail
because it was *misconfigured*, because the *transport* hiccuped (retryable),
because the provider returned something *unusable*, or because the returned
structured output *failed schema validation*. Messages never embed the prompt,
the provider key, request URLs, or raw response bodies, so that exception text
and tracebacks stay safe to log (see ``docs/security/security-baseline.md`` —
"Redact sensitive fields in errors and provider traces").
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for every LLM provider-layer failure."""


class LLMConfigurationError(LLMError):
    """Provider configuration is missing or invalid (no key, no base URL, ...).

    Not retryable: retrying the same misconfiguration cannot succeed.
    """


class LLMTransientError(LLMError):
    """A transport-level failure that may succeed if retried.

    Raised for timeouts, connection failures, and provider ``5xx`` responses.
    """


class LLMResponseError(LLMError):
    """The provider replied, but the reply was unusable.

    Raised for non-JSON bodies, missing expected fields, or non-retryable
    ``4xx`` responses (e.g. authentication failure). Not retried.
    """


class StructuredOutputValidationError(LLMError):
    """Provider output did not validate against the requested schema.

    This is the untrusted-analyst trust boundary failing closed: the output is
    rejected and never returned to callers as if it were trusted.
    """

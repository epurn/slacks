"""Build the configured :class:`Provider` from :class:`LLMSettings`.

This is the single place provider selection happens: the ``FATTY_LLM_PROVIDER``
value picks the adapter, and validated settings supply the key, model, base URL,
timeout, and retry bound. Callers depend only on the :class:`Provider`
interface, never on a concrete adapter.
"""

from __future__ import annotations

from app.llm.base import Provider
from app.llm.config import LLMSettings
from app.llm.errors import LLMConfigurationError
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.claude_code import ClaudeCodeProvider
from app.llm.providers.codex import CodexProvider
from app.llm.providers.fake import FakeProvider
from app.llm.providers.openai import OpenAIProvider


def build_provider(settings: LLMSettings) -> Provider:
    """Return the provider adapter selected by ``settings.provider``.

    ``LLMSettings`` has already validated that real providers carry a key and
    model (and that ``openai_compatible`` carries a base URL), so this function
    only maps the selector to a concrete adapter.
    """

    if settings.provider == "fake":
        return FakeProvider(
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            supports_vision=settings.supports_vision,
        )

    # Claude Code authenticates via its own local session, so it legitimately has
    # no Fatty-side key and an optional model. Build it *before* the
    # ``api_key is None`` guard, which must not reject it.
    if settings.provider == "claude_code":
        return ClaudeCodeProvider(
            model=settings.model,  # may be empty — Claude Code uses its session default
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )

    # Codex also authenticates through its local CLI state by default and accepts
    # an optional child-only API key, so it must be built before keyed-provider
    # guards. ``supports_vision`` is threaded for the shared image-capability gate.
    if settings.provider == "codex":
        return CodexProvider(
            model=settings.model,
            api_key=settings.api_key.get_secret_value() if settings.api_key else None,
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            supports_vision=settings.supports_vision,
        )

    if settings.provider == "anthropic":
        # Anthropic always requires a key; config.py already enforces this, but
        # the guard keeps the type checker honest and fails closed if that changes.
        if settings.api_key is None:
            raise LLMConfigurationError("provider 'anthropic' requires an API key")
        return AnthropicProvider(
            api_key=settings.api_key.get_secret_value(),
            model=settings.model,
            base_url=settings.resolved_base_url(),
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            supports_vision=settings.supports_vision,
        )

    # "openai" and "openai_compatible" share the Chat Completions wire format;
    # they differ only in the configured base URL. openai_compatible may run
    # keyless (local endpoint — Ollama, LM Studio, vLLM), so api_key may be None;
    # the adapter omits the Authorization header when no key is provided.
    api_key: str | None = settings.api_key.get_secret_value() if settings.api_key else None
    return OpenAIProvider(
        api_key=api_key,
        model=settings.model,
        base_url=settings.resolved_base_url(),
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
        supports_vision=settings.supports_vision,
    )

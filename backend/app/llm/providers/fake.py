"""In-memory fake provider.

The fake makes no network calls, so CI and local tests never hit a live model.
It returns scripted raw payloads (and can raise scripted transient errors) so
tests can exercise the full ``structured_completion`` flow — success, schema
validation, retries, and logging — deterministically. It records the prompts it
received so tests can assert on call behavior without inspecting logs.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from pydantic import BaseModel

from app.llm.base import Provider
from app.llm.errors import LLMConfigurationError, LLMError


class FakeProvider(Provider):
    """A scripted, network-free :class:`Provider` for tests and local dev.

    Args:
        responses: raw payloads returned by successive calls, in order. A list
            entry may be an :class:`LLMError` instance, which is raised instead
            of returned — use a transient error to drive the retry path.
        timeout_seconds: accepted for interface parity; the fake never waits.
        max_retries: retry bound applied by the base class.
    """

    name = "fake"

    def __init__(
        self,
        *,
        responses: list[dict[str, Any] | LLMError] | None = None,
        timeout_seconds: float = 1.0,
        max_retries: int = 0,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, max_retries=max_retries)
        self._responses: deque[dict[str, Any] | LLMError] = deque(responses or [])
        #: Prompts received, in order — for test assertions.
        self.prompts: list[str] = []

    def _complete(
        self, prompt: str, schema: type[BaseModel], *, timeout_seconds: float
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        if not self._responses:
            raise LLMConfigurationError("fake provider has no scripted response")
        item = self._responses.popleft()
        if isinstance(item, LLMError):
            raise item
        return item

"""In-memory fake provider.

The fake makes no network calls, so CI and local tests never hit a live model.
It returns scripted raw payloads (and can raise scripted transient errors) so
tests can exercise the full ``structured_completion`` flow — success, schema
validation, retries, and logging — deterministically. It records the prompts it
received so tests can assert on call behavior without inspecting logs.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from app.llm.base import ImageInput, Provider
from app.llm.errors import LLMConfigurationError, LLMError


class FakeProvider(Provider):
    """A scripted, network-free :class:`Provider` for tests and local dev.

    Args:
        responses: raw payloads returned by successive calls, in order. A list
            entry may be an :class:`LLMError` instance, which is raised instead
            of returned — use a transient error to drive the retry path.
        timeout_seconds: accepted for interface parity; the fake never waits.
        max_retries: retry bound applied by the base class.
        supports_vision: declares the fake as vision-capable so image input is
            accepted rather than rejected — used to stand in for a vision model
            in tests without any network call.
        sleep: injectable sleep seam forwarded to the base class. Pass a fake
            (e.g. ``sleeps.append``) to assert on backoff delays without any
            real wall-clock wait.
    """

    name = "fake"

    def __init__(
        self,
        *,
        responses: list[dict[str, Any] | LLMError] | None = None,
        timeout_seconds: float = 1.0,
        max_retries: int = 0,
        supports_vision: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        model: str = "",
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            supports_vision=supports_vision,
            sleep=sleep,
            model=model,
        )
        self._responses: deque[dict[str, Any] | LLMError] = deque(responses or [])
        #: Prompts received, in order — for test assertions.
        self.prompts: list[str] = []
        #: Image counts received per call, in order — lets tests assert images
        #: reached the provider without the fake ever retaining the bytes.
        self.image_counts: list[int] = []

    def _complete(
        self,
        prompt: str,
        schema: type[BaseModel],  # noqa: ARG002 — abstract _complete signature; fake ignores schema
        *,
        images: Sequence[ImageInput] | None,
        timeout_seconds: float,  # noqa: ARG002 — abstract _complete signature; fake ignores timeout
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.image_counts.append(len(images) if images else 0)
        if not self._responses:
            raise LLMConfigurationError("fake provider has no scripted response")
        item = self._responses.popleft()
        if isinstance(item, LLMError):
            raise item
        return item

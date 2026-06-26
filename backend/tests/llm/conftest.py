"""Shared fixtures and a synthetic schema for LLM provider tests."""

from __future__ import annotations

from pydantic import BaseModel


class Candidate(BaseModel):
    """A small synthetic structured-output schema used across provider tests."""

    name: str
    calories: int


def openai_completion(content: str) -> dict[str, object]:
    """Build a minimal OpenAI chat-completion response carrying ``content``."""

    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def anthropic_tool_response(tool_input: dict[str, object]) -> dict[str, object]:
    """Build a minimal Anthropic messages response carrying a ``tool_use`` block."""

    return {
        "content": [{"type": "tool_use", "name": "emit_structured_output", "input": tool_input}]
    }

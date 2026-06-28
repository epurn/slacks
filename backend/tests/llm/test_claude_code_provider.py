"""Claude Code adapter tests: invocation construction, error mapping, hygiene.

The subprocess is replaced by an injected runner seam, so these never spawn a
real process or touch a live Claude Code install.
"""

from __future__ import annotations

import logging
import subprocess

import pytest

from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.llm.providers.claude_code import (
    ClaudeCodeProvider,
    ClaudeCodeResult,
    Invocation,
)
from tests.llm.conftest import Candidate, sample_image

#: A marker that stands in for personal context in the prompt. It must never
#: appear in argv, logs, or error messages.
SENSITIVE_PROMPT = "SENSITIVE_PROMPT_two boiled eggs and toast"


def _result(returncode: int = 0, stdout: str = "", stderr: str = "") -> ClaudeCodeResult:
    return ClaudeCodeResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _provider(runner: object, *, model: str = "", max_retries: int = 0) -> ClaudeCodeProvider:
    return ClaudeCodeProvider(
        model=model,
        timeout_seconds=5.0,
        max_retries=max_retries,
        binary="claude",
        runner=runner,  # type: ignore[arg-type]
    )


def test_success_returns_validated_object() -> None:
    captured: dict[str, Invocation] = {}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        captured["invocation"] = invocation
        return _result(stdout='{"name": "apple", "calories": 95}')

    result = _provider(runner).structured_completion("an apple", Candidate)

    assert result == Candidate(name="apple", calories=95)
    # The prompt travels on stdin, never argv.
    assert "an apple" in captured["invocation"].stdin
    assert all("an apple" not in arg for arg in captured["invocation"].argv)


def test_invocation_disables_all_tools() -> None:
    invocation = _provider(lambda *a, **k: _result()).build_invocation("an apple", Candidate)
    argv = invocation.argv

    # Headless print mode.
    assert "--print" in argv
    # Empty allow-list: the value immediately after --allowed-tools is "".
    assert argv[argv.index("--allowed-tools") + 1] == ""
    # Every built-in tool is explicitly denied.
    denied = argv[argv.index("--disallowed-tools") + 1]
    for tool in ("Bash", "Read", "Edit", "Write", "WebFetch", "WebSearch"):
        assert tool in denied
    # Permissions are never bypassed.
    assert argv[argv.index("--permission-mode") + 1] == "default"
    assert "bypassPermissions" not in argv
    assert "--dangerously-skip-permissions" not in argv
    # No MCP servers are loaded.
    assert "--strict-mcp-config" in argv


def test_model_is_passed_through_when_set() -> None:
    invocation = _provider(lambda *a, **k: _result(), model="claude-sonnet-4-5").build_invocation(
        "an apple", Candidate
    )

    assert "--model" in invocation.argv
    assert invocation.argv[invocation.argv.index("--model") + 1] == "claude-sonnet-4-5"


def test_model_is_omitted_when_empty() -> None:
    invocation = _provider(lambda *a, **k: _result()).build_invocation("an apple", Candidate)

    assert "--model" not in invocation.argv


def test_missing_binary_is_a_configuration_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        raise FileNotFoundError("claude")

    with pytest.raises(LLMConfigurationError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_unauthenticated_is_a_configuration_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr="Error: you are not logged in")

    with pytest.raises(LLMConfigurationError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_timeout_is_transient_and_retried_to_the_bound() -> None:
    calls = {"n": 0}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout_seconds)

    with pytest.raises(LLMTransientError):
        _provider(runner, max_retries=2).structured_completion("an apple", Candidate)

    # First attempt + 2 retries.
    assert calls["n"] == 3


def test_spawn_failure_is_transient() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        raise OSError("exec format error")

    with pytest.raises(LLMTransientError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_nonzero_exit_is_a_response_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=2, stderr="some internal failure")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_non_json_stdout_is_a_response_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(stdout="not json at all")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_non_object_json_stdout_is_a_response_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(stdout="[1, 2, 3]")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_schema_invalid_json_is_rejected_by_base_class() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        # Well-formed JSON object, but "calories" is the wrong type.
        return _result(stdout='{"name": "apple", "calories": "many"}')

    with pytest.raises(StructuredOutputValidationError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_image_input_fails_fast() -> None:
    # Vision via claude_code is a non-goal: it must fail, not silently drop the
    # image. Bypass the base-class vision gate by reaching _complete directly.
    provider = _provider(lambda *a, **k: _result())

    with pytest.raises(LLMConfigurationError):
        provider._complete(
            "an apple",
            Candidate,
            images=[sample_image()],
            timeout_seconds=5.0,
        )


def test_nothing_sensitive_is_logged_or_surfaced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A failing call must not leak the prompt or the raw model output anywhere.
    raw_response = '{"name": "apple", "calories": "secret-leak-value"}'

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(stdout=raw_response)

    with caplog.at_level(logging.DEBUG, logger="app.llm"):
        try:
            _provider(runner).structured_completion(SENSITIVE_PROMPT, Candidate)
        except StructuredOutputValidationError as exc:
            assert SENSITIVE_PROMPT not in str(exc)
            assert "secret-leak-value" not in str(exc)

    log_text = caplog.text
    assert SENSITIVE_PROMPT not in log_text
    assert "secret-leak-value" not in log_text

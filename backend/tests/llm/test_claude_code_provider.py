"""Claude Code adapter tests: invocation construction, error mapping, hygiene.

The subprocess is replaced by an injected runner seam, so these never spawn a
real process or touch a live Claude Code install.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.llm.providers.claude_code import (
    _ENV_ALLOWLIST,
    MAX_STDOUT_BYTES,
    ClaudeCodeProvider,
    ClaudeCodeResult,
    Invocation,
    _parse_object,
    run_claude_code,
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


def _vision_provider(runner: object) -> ClaudeCodeProvider:
    """A provider whose configured session is declared vision-capable (FTY-412)."""

    return ClaudeCodeProvider(
        timeout_seconds=5.0,
        max_retries=0,
        supports_vision=True,
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


# --- Image input (FTY-412) ---


def _stream_json_transcript(result_text: str) -> str:
    """A minimal stream-json NDJSON transcript ending in a success result event."""

    return "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text"}]}}),
            json.dumps(
                {"type": "result", "subtype": "success", "is_error": False, "result": result_text}
            ),
        ]
    )


def test_image_input_fails_fast_when_model_is_not_vision_capable() -> None:
    # Not declared vision-capable: fail closed rather than silently dropping the
    # image. Bypass the base-class gate by reaching _complete directly.
    provider = _provider(lambda *a, **k: _result())

    with pytest.raises(LLMConfigurationError):
        provider._complete(
            "an apple",
            Candidate,
            images=[sample_image()],
            timeout_seconds=5.0,
        )


def test_vision_call_sends_the_image_and_returns_a_validated_object() -> None:
    """A vision-capable session reads an image through the stream-json channel.

    This is the FTY-412 regression: label scanning was impossible on every
    ``claude_code`` deployment because the adapter refused image input outright,
    so the label step's one vision call always failed closed.
    """

    captured: dict[str, Invocation] = {}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        captured["invocation"] = invocation
        return _result(stdout=_stream_json_transcript('{"name": "apple", "calories": 95}'))

    provider = _vision_provider(runner)
    result = provider.structured_completion("read this", Candidate, images=[sample_image()])

    assert result == Candidate(name="apple", calories=95)

    invocation = captured["invocation"]
    # Images can only be supplied through the streaming channel.
    assert "--input-format" in invocation.argv
    assert "stream-json" in invocation.argv
    # The image travels on stdin as a base64 block — never in argv, never a file.
    message = json.loads(invocation.stdin)
    content = message["message"]["content"]
    assert content[0]["type"] == "text"
    image_block = content[1]
    assert image_block["type"] == "image"
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(image_block["source"]["data"]) == sample_image().data


def test_vision_invocation_still_disables_all_tools() -> None:
    # The streaming channel must not weaken the injection posture: text printed
    # on an uploaded label is data, and no tool may act on it.
    invocation = _vision_provider(lambda *a, **k: _result()).build_invocation(
        "read this", Candidate, images=[sample_image()]
    )
    argv = invocation.argv

    assert argv[argv.index("--allowed-tools") + 1] == ""
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--permission-mode") + 1] == "default"


def test_text_only_invocation_is_unchanged_by_vision_support() -> None:
    # The text path must stay byte-for-byte as it was (llm-provider.md).
    invocation = _vision_provider(lambda *a, **k: _result()).build_invocation("an apple", Candidate)

    assert invocation.argv[invocation.argv.index("--output-format") + 1] == "text"
    assert "--input-format" not in invocation.argv
    assert invocation.stdin.startswith("an apple")


def test_image_bytes_never_appear_in_argv() -> None:
    invocation = _vision_provider(lambda *a, **k: _result()).build_invocation(
        SENSITIVE_PROMPT, Candidate, images=[sample_image()]
    )

    encoded = base64.b64encode(sample_image().data).decode("ascii")
    assert all(encoded not in arg for arg in invocation.argv)
    assert all(SENSITIVE_PROMPT not in arg for arg in invocation.argv)


def test_stream_json_error_result_is_a_response_error() -> None:
    transcript = json.dumps(
        {"type": "result", "subtype": "error_during_execution", "is_error": True}
    )

    with pytest.raises(LLMResponseError):
        _vision_provider(lambda *a, **k: _result(stdout=transcript)).structured_completion(
            "read this", Candidate, images=[sample_image()]
        )


def test_stream_json_without_a_result_event_is_a_response_error() -> None:
    transcript = json.dumps({"type": "system", "subtype": "init"})

    with pytest.raises(LLMResponseError):
        _vision_provider(lambda *a, **k: _result(stdout=transcript)).structured_completion(
            "read this", Candidate, images=[sample_image()]
        )


def test_stream_json_error_message_does_not_echo_the_transcript() -> None:
    # A transcript can carry text transcribed from an untrusted label image.
    transcribed = "SENSITIVE_LABEL_TEXT"
    transcript = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": transcribed,
        }
    )

    with pytest.raises(LLMResponseError) as excinfo:
        _vision_provider(lambda *a, **k: _result(stdout=transcript)).structured_completion(
            "read this", Candidate, images=[sample_image()]
        )

    assert transcribed not in str(excinfo.value)


# --- Tolerant JSON extraction tests (_parse_object) ---


def test_parse_object_bare_json_unchanged() -> None:
    # (d) A bare JSON object parses to the same dict as before.
    result = _parse_object('{"name": "apple", "calories": 95}')
    assert result == {"name": "apple", "calories": 95}


def test_parse_object_json_fenced() -> None:
    # (a) A ```json ... ``` fence is stripped and the object parses correctly.
    fenced = '```json\n{"name": "apple", "calories": 95}\n```'
    result = _parse_object(fenced)
    assert result == {"name": "apple", "calories": 95}


def test_parse_object_plain_fence() -> None:
    # ``` without a language tag is also stripped.
    fenced = '```\n{"name": "apple", "calories": 95}\n```'
    result = _parse_object(fenced)
    assert result == {"name": "apple", "calories": 95}


def test_parse_object_prose_prefix() -> None:
    # (b) A leading prose line before the object parses correctly.
    with_prose = 'Here is the JSON:\n{"name": "apple", "calories": 95}'
    result = _parse_object(with_prose)
    assert result == {"name": "apple", "calories": 95}


def test_parse_object_trailing_junk_rejected() -> None:
    # (c) Non-whitespace trailing the object is rejected.
    with_junk = '{"name": "apple", "calories": 95}\nsome trailing text'
    with pytest.raises(LLMResponseError):
        _parse_object(with_junk)


def test_parse_object_trailing_whitespace_accepted() -> None:
    # Trailing whitespace only (newlines/spaces) after the object is fine.
    result = _parse_object('{"name": "apple", "calories": 95}\n  \n')
    assert result == {"name": "apple", "calories": 95}


def test_parse_object_non_json_is_response_error() -> None:
    # (e) Non-JSON output raises LLMResponseError.
    with pytest.raises(LLMResponseError):
        _parse_object("not json at all")


def test_parse_object_non_object_json_is_response_error() -> None:
    # (e) A JSON array raises LLMResponseError (no top-level object).
    with pytest.raises(LLMResponseError):
        _parse_object("[1, 2, 3]")


def test_parse_object_extraction_does_not_echo_content() -> None:
    # The error message must never echo the stdout content (which may carry
    # untrusted food-log text).
    sensitive = "SENSITIVE_FOOD_LOG_CONTENT"
    with pytest.raises(LLMResponseError) as exc_info:
        _parse_object(f"not json — {sensitive}")
    assert sensitive not in str(exc_info.value)


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


# ---------------------------------------------------------------------------
# FTY-131: Env allowlist — subprocess receives only the allowed keys
# ---------------------------------------------------------------------------


def _capture_subprocess_env() -> tuple[dict[str, str], MagicMock]:
    """Return (captured_env_dict, fake_subprocess_run) for env-allowlist tests.

    The fake ``subprocess.run`` records the ``env=`` kwarg into ``captured_env``
    and returns a zero-returncode completed-process mock.
    """
    captured: dict[str, str] = {}

    fake_completed = MagicMock()
    fake_completed.returncode = 0
    fake_completed.stdout = ""
    fake_completed.stderr = ""

    def fake_run(
        *args: object,
        env: dict[str, str] | None = None,
        **kwargs: object,
    ) -> MagicMock:
        if env is not None:
            captured.update(env)
        return fake_completed

    return captured, fake_run  # type: ignore[return-value]


def test_env_allowlist_excludes_slacks_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Inject known secrets into the process environment, then verify none reach
    # the subprocess via the env= argument that run_claude_code builds.
    secret_vars = {
        "SLACKS_AUTH_SECRET": "hmac-key-must-not-leak",
        "POSTGRES_PASSWORD": "db-pw-must-not-leak",
        "SLACKS_FDC_API_KEY": "fdc-key-must-not-leak",
        "SLACKS_SEARCH_API_KEY": "search-key-must-not-leak",
    }
    for k, v in secret_vars.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("USER", "slacksuser")
    monkeypatch.setenv("LOGNAME", "slacksuser")

    captured_env, fake_run = _capture_subprocess_env()
    invocation = Invocation(argv=("claude", "--print"), stdin="test")

    with patch("app.llm.providers.claude_code.subprocess.run", side_effect=fake_run):
        run_claude_code(invocation, timeout_seconds=5.0)

    for key in secret_vars:
        assert key not in captured_env, f"Secret {key!r} must not reach the subprocess"
    assert captured_env.get("USER") == "slacksuser"
    assert captured_env.get("LOGNAME") == "slacksuser"


def test_env_allowlist_forwards_required_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    # Required vars present in the parent environment must reach the child.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/slacksuser")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/claude-config")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("USER", "slacksuser")
    monkeypatch.setenv("LOGNAME", "slacksuser")

    captured_env, fake_run = _capture_subprocess_env()
    invocation = Invocation(argv=("claude", "--print"), stdin="test")

    with patch("app.llm.providers.claude_code.subprocess.run", side_effect=fake_run):
        run_claude_code(invocation, timeout_seconds=5.0)

    assert captured_env.get("PATH") == "/usr/bin:/bin"
    assert captured_env.get("HOME") == "/home/slacksuser"
    assert captured_env.get("CLAUDE_CONFIG_DIR") == "/claude-config"
    assert captured_env.get("LANG") == "en_US.UTF-8"
    assert captured_env.get("USER") == "slacksuser"
    assert captured_env.get("LOGNAME") == "slacksuser"


def test_env_allowlist_omits_absent_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    # A var in the allowlist that is absent from the parent must not be invented.
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)

    captured_env, fake_run = _capture_subprocess_env()
    invocation = Invocation(argv=("claude", "--print"), stdin="test")

    with patch("app.llm.providers.claude_code.subprocess.run", side_effect=fake_run):
        run_claude_code(invocation, timeout_seconds=5.0)

    assert "CLAUDE_CONFIG_DIR" not in captured_env
    assert "TMPDIR" not in captured_env
    assert "USER" not in captured_env
    assert "LOGNAME" not in captured_env


def test_env_allowlist_contains_no_slacks_or_postgres_keys() -> None:
    # Sanity-check the constant itself: it must never contain SLACKS_ or POSTGRES_.
    for key in _ENV_ALLOWLIST:
        assert not key.startswith("SLACKS_"), f"{key!r} is a Slacks secret key"
        assert not key.startswith("POSTGRES_"), f"{key!r} is a Postgres secret key"


def test_env_allowlist_pinned_key_set() -> None:
    # Pin the exact expected key set so a future edit that drops a required key
    # or silently re-adds a secret-bearing one fails this test.
    expected = frozenset(
        {
            "PATH",
            "HOME",
            "CLAUDE_CONFIG_DIR",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TMPDIR",
            "USER",
            "LOGNAME",
        }
    )
    assert expected == _ENV_ALLOWLIST


# ---------------------------------------------------------------------------
# FTY-131: Stdout size cap
# ---------------------------------------------------------------------------


def test_oversized_stdout_raises_response_error() -> None:
    # A stdout exceeding MAX_STDOUT_BYTES must raise a non-retryable error.
    oversized = "x" * (MAX_STDOUT_BYTES + 1)

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=0, stdout=oversized)

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_oversized_stdout_error_is_content_free() -> None:
    # The error message must never echo the oversized (potentially hostile) content.
    oversized = "HOSTILE_CONTENT_" * (MAX_STDOUT_BYTES // len("HOSTILE_CONTENT_") + 1)

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=0, stdout=oversized)

    with pytest.raises(LLMResponseError) as exc_info:
        _provider(runner).structured_completion("an apple", Candidate)

    assert "HOSTILE_CONTENT_" not in str(exc_info.value)


def test_at_cap_stdout_parses_successfully() -> None:
    # A stdout exactly at the cap (valid JSON) must parse without error.
    valid_json = '{"name": "apple", "calories": 95}'
    # Pad to exactly MAX_STDOUT_BYTES with trailing whitespace (accepted by _parse_object).
    padded = valid_json + " " * (MAX_STDOUT_BYTES - len(valid_json))
    assert len(padded) == MAX_STDOUT_BYTES

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=0, stdout=padded)

    result = _provider(runner).structured_completion("an apple", Candidate)
    assert result == Candidate(name="apple", calories=95)


# ---------------------------------------------------------------------------
# FTY-131: Transient exit classification
# ---------------------------------------------------------------------------


def test_rate_limited_exit_is_transient() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr="Error: rate limited, please wait")

    with pytest.raises(LLMTransientError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_overloaded_exit_is_transient() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr="API error: overloaded")

    with pytest.raises(LLMTransientError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_temporarily_unavailable_exit_is_transient() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr="Service is temporarily unavailable")

    with pytest.raises(LLMTransientError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_generic_nonzero_exit_is_response_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr="some internal error occurred")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_transient_is_retried_to_the_bound() -> None:
    calls = {"n": 0}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        calls["n"] += 1
        return _result(returncode=1, stderr="rate limited")

    with pytest.raises(LLMTransientError):
        _provider(runner, max_retries=2).structured_completion("an apple", Candidate)

    assert calls["n"] == 3  # first attempt + 2 retries


def test_transient_error_message_does_not_echo_stderr() -> None:
    sensitive_stderr = "SENSITIVE_RATE_LIMIT_DETAIL"

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr=f"rate limited: {sensitive_stderr}")

    with pytest.raises(LLMTransientError) as exc_info:
        _provider(runner).structured_completion("an apple", Candidate)

    assert sensitive_stderr not in str(exc_info.value)


# ---------------------------------------------------------------------------
# FTY-131: Auth marker anchoring — no false positives from bare "login"
# ---------------------------------------------------------------------------


def test_unrelated_login_word_in_stderr_is_not_auth_failure() -> None:
    # Bare "login" inside an unrelated word/sentence must NOT trigger auth classification.
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        # Contains "login" as part of an unrelated error, not a Claude auth message.
        return _result(returncode=1, stderr="Failed to contact loginservice.example.com")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_unrelated_log_in_phrase_is_not_auth_failure() -> None:
    # "log in" in a generic, unrelated context must NOT trigger auth classification.
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr="Users must log in to the wiki to edit pages")

    # "Users must log in" does NOT contain "please log in" → falls through to response error.
    with pytest.raises((LLMResponseError, LLMTransientError)):
        _provider(runner).structured_completion("an apple", Candidate)


def test_not_logged_in_is_auth_classified() -> None:
    # "not logged in" (actual Claude Code auth error) must trigger auth classification.
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr="Not logged in · Please run /login")

    with pytest.raises(LLMConfigurationError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_please_run_login_is_auth_classified() -> None:
    # "please run /login" (Claude Code CLI instruction) must trigger auth classification.
    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr="Error: please run /login to authenticate")

    with pytest.raises(LLMConfigurationError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_auth_error_message_does_not_echo_stderr() -> None:
    # The auth error message must be content-free (no stderr echoed).
    sensitive_stderr = "SENSITIVE_SESSION_DETAIL"

    def runner(invocation: Invocation, *, timeout_seconds: float) -> ClaudeCodeResult:
        return _result(returncode=1, stderr=f"not logged in: {sensitive_stderr}")

    with pytest.raises(LLMConfigurationError) as exc_info:
        _provider(runner).structured_completion("an apple", Candidate)

    assert sensitive_stderr not in str(exc_info.value)

"""Codex adapter tests: safe invocation, env hygiene, error mapping."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.llm.providers.codex import (
    _ENV_ALLOWLIST,
    CodexProvider,
    CodexResult,
    Invocation,
    run_codex,
)
from tests.llm.conftest import Candidate, sample_image

SENSITIVE_PROMPT = "SENSITIVE_PROMPT_two boiled eggs and toast"
SENSITIVE_KEY = "codex-child-secret-must-not-leak"
SENSITIVE_OUTPUT = "SENSITIVE_CODEX_OUTPUT_must_not_leak"


def _result(returncode: int = 0, stdout: str = "", stderr: str = "") -> CodexResult:
    return CodexResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _provider(
    runner: object,
    *,
    model: str = "",
    api_key: str | None = None,
    max_retries: int = 0,
    supports_vision: bool = False,
) -> CodexProvider:
    return CodexProvider(
        model=model,
        api_key=api_key,
        timeout_seconds=5.0,
        max_retries=max_retries,
        supports_vision=supports_vision,
        binary="codex",
        runner=runner,  # type: ignore[arg-type]
    )


def test_success_returns_schema_validated_object() -> None:
    captured: dict[str, Invocation] = {}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        captured["invocation"] = invocation
        return _result(stdout='{"name": "apple", "calories": 95}')

    result = _provider(runner).structured_completion("an apple", Candidate)

    assert result == Candidate(name="apple", calories=95)
    assert captured["invocation"].stdin == "an apple"
    assert all("an apple" not in arg for arg in captured["invocation"].argv)


def test_invocation_uses_safe_flags_and_stdin_prompt() -> None:
    captured: dict[str, Invocation] = {}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        captured["invocation"] = invocation
        return _result(stdout='{"name": "apple", "calories": 95}')

    _provider(runner).structured_completion(SENSITIVE_PROMPT, Candidate)

    invocation = captured["invocation"]
    argv = invocation.argv
    assert argv[:2] == ("codex", "exec")
    for flag in (
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--output-schema",
    ):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--ask-for-approval") + 1] == "never"
    assert argv[argv.index("-c") + 1] == 'web_search="disabled"'
    assert argv[-1] == "-"
    assert invocation.stdin == SENSITIVE_PROMPT
    assert all(SENSITIVE_PROMPT not in arg for arg in argv)
    assert "--model" not in argv


def test_model_flag_is_present_only_when_configured() -> None:
    captured_with_model: dict[str, Invocation] = {}
    captured_without_model: dict[str, Invocation] = {}

    def with_model_runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        captured_with_model["invocation"] = invocation
        return _result(stdout='{"name": "apple", "calories": 95}')

    def without_model_runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        captured_without_model["invocation"] = invocation
        return _result(stdout='{"name": "apple", "calories": 95}')

    _provider(with_model_runner, model="gpt-5-codex").structured_completion("an apple", Candidate)
    _provider(without_model_runner).structured_completion("an apple", Candidate)

    argv = captured_with_model["invocation"].argv
    assert argv[argv.index("--model") + 1] == "gpt-5-codex"
    assert "--model" not in captured_without_model["invocation"].argv


def test_schema_file_is_generated_and_temp_tree_is_cleaned_up() -> None:
    captured_schema_path: dict[str, Path] = {}
    captured_temp_root: dict[str, Path] = {}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        schema_path = Path(invocation.argv[invocation.argv.index("--output-schema") + 1])
        workdir = Path(invocation.cwd)
        captured_schema_path["path"] = schema_path
        captured_temp_root["path"] = schema_path.parent

        assert schema_path.exists()
        assert schema_path.parent == workdir.parent
        assert workdir.exists()
        assert list(workdir.iterdir()) == []
        assert not (workdir / "AGENTS.md").exists()
        assert not (workdir / ".codex").exists()
        assert Path(__file__).resolve().parents[3] not in workdir.parents

        schema_json = schema_path.read_text(encoding="utf-8")
        parsed_schema = json.loads(schema_json)
        assert parsed_schema["properties"]["name"]["type"] == "string"
        assert parsed_schema["properties"]["calories"]["type"] == "integer"
        assert SENSITIVE_PROMPT not in schema_json
        assert SENSITIVE_KEY not in schema_json
        return _result(stdout='{"name": "apple", "calories": 95}')

    _provider(runner, api_key=SENSITIVE_KEY).structured_completion(SENSITIVE_PROMPT, Candidate)

    assert not captured_schema_path["path"].exists()
    assert not captured_temp_root["path"].exists()


def test_temp_tree_is_cleaned_up_after_failure() -> None:
    captured_temp_root: dict[str, Path] = {}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        schema_path = Path(invocation.argv[invocation.argv.index("--output-schema") + 1])
        captured_temp_root["path"] = schema_path.parent
        assert schema_path.exists()
        return _result(stdout="not json")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)

    assert not captured_temp_root["path"].exists()


def test_subprocess_runner_uses_no_shell_and_forwards_invocation_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    invocation = Invocation(
        argv=("codex", "exec", "-"),
        stdin=SENSITIVE_PROMPT,
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin"},
    )
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout='{"name": "apple", "calories": 95}',
            stderr="",
        )

    with patch("app.llm.providers.codex.subprocess.run", side_effect=fake_run):
        result = run_codex(invocation, timeout_seconds=5.0)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert "shell" not in kwargs
    assert kwargs["input"] == SENSITIVE_PROMPT
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
    assert result.returncode == 0


def test_child_env_allowlist_excludes_parent_secrets_and_uses_child_only_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_vars = {
        "FATTY_AUTH_SECRET": "auth-secret-must-not-leak",
        "FATTY_LLM_API_KEY": "fatty-llm-key-must-not-leak",
        "POSTGRES_PASSWORD": "postgres-password-must-not-leak",
        "FATTY_FDC_API_KEY": "fdc-key-must-not-leak",
        "FATTY_SEARCH_API_KEY": "search-key-must-not-leak",
        "OPENAI_API_KEY": "openai-key-must-not-leak",
        "ARBITRARY_PARENT_SECRET": "arbitrary-secret-must-not-leak",
        "CODEX_API_KEY": "parent-codex-key-must-not-leak",
    }
    for key, value in secret_vars.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/fatty")
    monkeypatch.setenv("CODEX_HOME", "/codex-home")
    monkeypatch.setenv("CODEX_SQLITE_HOME", "/codex-sqlite")
    monkeypatch.setenv("CODEX_CA_CERTIFICATE", "/certs/ca.pem")
    monkeypatch.setenv("SSL_CERT_FILE", "/certs/ssl.pem")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    captured_env: dict[str, str] = {}
    captured_argv: dict[str, tuple[str, ...]] = {}

    def fake_run(
        *args: object,
        env: dict[str, str] | None = None,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if env is not None:
            captured_env.update(env)
        argv = args[0]
        assert isinstance(argv, list)
        captured_argv["argv"] = tuple(argv)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout='{"name": "apple", "calories": 95}',
            stderr="",
        )

    with patch("app.llm.providers.codex.subprocess.run", side_effect=fake_run):
        result = CodexProvider(
            model="",
            api_key=SENSITIVE_KEY,
            timeout_seconds=5.0,
            max_retries=0,
        ).structured_completion("an apple", Candidate)

    assert result == Candidate(name="apple", calories=95)
    assert captured_env["CODEX_API_KEY"] == SENSITIVE_KEY
    for key in secret_vars:
        if key != "CODEX_API_KEY":
            assert key not in captured_env
    assert captured_env["PATH"] == "/usr/bin:/bin"
    assert captured_env["HOME"] == "/home/fatty"
    assert captured_env["CODEX_HOME"] == "/codex-home"
    assert captured_env["CODEX_SQLITE_HOME"] == "/codex-sqlite"
    assert captured_env["CODEX_CA_CERTIFICATE"] == "/certs/ca.pem"
    assert captured_env["SSL_CERT_FILE"] == "/certs/ssl.pem"
    assert captured_env["LANG"] == "en_US.UTF-8"
    assert captured_env["TMPDIR"] == str(tmp_path)
    assert all(SENSITIVE_KEY not in arg for arg in captured_argv["argv"])


def test_parent_codex_api_key_is_not_forwarded_without_settings_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_API_KEY", "parent-codex-key-must-not-leak")
    captured_env: dict[str, str] = {}

    def fake_run(
        *args: object,
        env: dict[str, str] | None = None,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if env is not None:
            captured_env.update(env)
        return subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout='{"name": "apple", "calories": 95}',
            stderr="",
        )

    with patch("app.llm.providers.codex.subprocess.run", side_effect=fake_run):
        CodexProvider(timeout_seconds=5.0, max_retries=0).structured_completion(
            "an apple", Candidate
        )

    assert "CODEX_API_KEY" not in captured_env


def test_env_allowlist_contains_no_disallowed_secret_prefixes() -> None:
    for key in _ENV_ALLOWLIST:
        assert not key.startswith("FATTY_")
        assert not key.startswith("POSTGRES_")
        assert key != "OPENAI_API_KEY"
        assert "SECRET" not in key


def test_missing_binary_is_configuration_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        raise FileNotFoundError("codex")

    with pytest.raises(LLMConfigurationError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_auth_failure_is_configuration_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(returncode=1, stderr="authentication failed")

    with pytest.raises(LLMConfigurationError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_timeout_is_transient_and_retried_to_bound() -> None:
    calls = {"n": 0}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd="codex", timeout=timeout_seconds)

    with pytest.raises(LLMTransientError):
        _provider(runner, max_retries=2).structured_completion("an apple", Candidate)

    assert calls["n"] == 3


def test_spawn_failure_is_transient() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        raise OSError("exec format error")

    with pytest.raises(LLMTransientError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_rate_limit_overload_and_unavailable_are_transient() -> None:
    for stderr in (
        "rate limited, please wait",
        "API overloaded",
        "service temporarily unavailable",
    ):

        def runner(
            invocation: Invocation,
            *,
            timeout_seconds: float,
            stderr_text: str = stderr,
        ) -> CodexResult:
            return _result(returncode=1, stderr=stderr_text)

        with pytest.raises(LLMTransientError):
            _provider(runner).structured_completion("an apple", Candidate)


def test_generic_nonzero_exit_is_response_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(returncode=2, stderr="internal failure")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_non_json_stdout_is_response_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(stdout="not json at all")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_non_object_stdout_is_response_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(stdout="[1, 2, 3]")

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_trailing_junk_stdout_is_response_error() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(stdout='{"name": "apple", "calories": 95}\ntrailing junk')

    with pytest.raises(LLMResponseError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_leading_and_trailing_whitespace_are_accepted() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(stdout=' \n {"name": "apple", "calories": 95}\n  ')

    result = _provider(runner).structured_completion("an apple", Candidate)

    assert result == Candidate(name="apple", calories=95)


def test_schema_invalid_json_is_rejected_by_base_class() -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(stdout='{"name": "apple", "calories": "many"}')

    with pytest.raises(StructuredOutputValidationError):
        _provider(runner).structured_completion("an apple", Candidate)


def test_images_fail_fast_without_spawning() -> None:
    calls = {"n": 0}

    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        calls["n"] += 1
        return _result(stdout='{"name": "apple", "calories": 95}')

    with pytest.raises(LLMConfigurationError):
        _provider(runner, supports_vision=True).structured_completion(
            "read this label",
            Candidate,
            images=[sample_image()],
        )

    assert calls["n"] == 0


def test_errors_and_logs_do_not_echo_prompt_output_key_or_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(
            returncode=2,
            stdout=SENSITIVE_OUTPUT,
            stderr=f"internal failure: {SENSITIVE_OUTPUT}",
        )

    with (
        caplog.at_level(logging.DEBUG, logger="app.llm"),
        pytest.raises(LLMResponseError) as exc_info,
    ):
        _provider(runner, api_key=SENSITIVE_KEY).structured_completion(
            SENSITIVE_PROMPT,
            Candidate,
        )

    exception_text = str(exc_info.value)
    log_text = caplog.text
    for sensitive in (SENSITIVE_PROMPT, SENSITIVE_OUTPUT, SENSITIVE_KEY):
        assert sensitive not in exception_text
        assert sensitive not in log_text


def test_validation_logs_do_not_echo_invalid_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_response = f'{{"name": "apple", "calories": "{SENSITIVE_OUTPUT}"}}'

    def runner(invocation: Invocation, *, timeout_seconds: float) -> CodexResult:
        return _result(stdout=raw_response)

    with (
        caplog.at_level(logging.DEBUG, logger="app.llm"),
        pytest.raises(StructuredOutputValidationError) as exc_info,
    ):
        _provider(runner, api_key=SENSITIVE_KEY).structured_completion(
            SENSITIVE_PROMPT,
            Candidate,
        )

    exception_text = str(exc_info.value)
    log_text = caplog.text
    for sensitive in (SENSITIVE_PROMPT, SENSITIVE_OUTPUT, SENSITIVE_KEY):
        assert sensitive not in exception_text
        assert sensitive not in log_text

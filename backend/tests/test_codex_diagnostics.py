"""Diagnostics tests for the codex provider capability descriptor (FTY-296).

Asserts the /healthz/sources codex entry:
  - correct enabled/available booleans across present/absent CLI and auth;
  - no key, token, account identity, auth path, or raw CLI output in the response;
  - no live codex invocation in any code path tested here.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.schemas.sources import SourceCapability, SourcesStatus
from app.services import sources as sources_service
from app.services.sources import _codex_saved_auth_present, _probe_codex


def _which(name: str) -> str | None:
    if name == "codex":
        return "/usr/bin/codex"
    return None


def _codex_cap(result: SourcesStatus) -> SourceCapability | None:
    for cap in result.sources:
        if cap.id == "codex":
            return cap
    return None


def test_codex_saved_auth_present_nonexistent_home(tmp_path: Path) -> None:
    assert _codex_saved_auth_present(str(tmp_path / "does-not-exist")) is False


def test_codex_saved_auth_present_empty_home(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    assert _codex_saved_auth_present(str(codex_home)) is False


def test_codex_saved_auth_present_ignores_non_auth_files(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "session.log").write_text("not auth", encoding="utf-8")
    assert _codex_saved_auth_present(str(codex_home)) is False


def test_codex_saved_auth_present_auth_file(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    assert _codex_saved_auth_present(str(codex_home)) is True


def test_codex_saved_auth_check_does_not_read_file_content(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        '{"token": "SECRET-TOKEN-MUST-NOT-BE-READ"}',
        encoding="utf-8",
    )

    with patch("builtins.open", side_effect=AssertionError("auth check must not read files")):
        result = _codex_saved_auth_present(str(codex_home))

    assert result is True


def test_probe_codex_binary_absent() -> None:
    with patch("app.services.sources.shutil.which", return_value=None):
        binary, auth = _probe_codex({})
    assert binary is False
    assert auth is False


def test_probe_codex_binary_present_no_auth(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    env = {"CODEX_HOME": str(codex_home)}
    with patch("app.services.sources.shutil.which", side_effect=_which):
        binary, auth = _probe_codex(env)
    assert binary is True
    assert auth is False


def test_probe_codex_binary_present_with_saved_auth(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    env = {"CODEX_HOME": str(codex_home)}
    with patch("app.services.sources.shutil.which", side_effect=_which):
        binary, auth = _probe_codex(env)
    assert binary is True
    assert auth is True


def test_probe_codex_binary_present_with_fatty_api_key(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    env = {
        "FATTY_LLM_PROVIDER": "codex",
        "CODEX_HOME": str(codex_home),
        "FATTY_LLM_API_KEY": "codex-child-key-must-not-leak",
    }
    with patch("app.services.sources.shutil.which", side_effect=_which):
        binary, auth = _probe_codex(env)
    assert binary is True
    assert auth is True


def test_probe_codex_default_home_when_env_unset(tmp_path: Path) -> None:
    with (
        patch("app.services.sources.shutil.which", side_effect=_which),
        patch("app.services.sources.os.path.expanduser", return_value=str(tmp_path / "no-auth")),
    ):
        binary, auth = _probe_codex({})
    assert binary is True
    assert auth is False


def test_codex_descriptor_present() -> None:
    with patch("app.services.sources.shutil.which", return_value=None):
        result = sources_service.list_source_capabilities({})
    assert _codex_cap(result) is not None


def test_codex_enabled_when_selected_with_saved_auth(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    env = {"FATTY_LLM_PROVIDER": "codex", "CODEX_HOME": str(codex_home)}
    with patch("app.services.sources.shutil.which", side_effect=_which):
        result = sources_service.list_source_capabilities(env)
    cap = _codex_cap(result)
    assert cap is not None
    assert cap.enabled is True
    assert cap.available is True


def test_codex_available_false_when_binary_absent(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    env = {"FATTY_LLM_PROVIDER": "codex", "CODEX_HOME": str(codex_home)}
    with patch("app.services.sources.shutil.which", return_value=None):
        result = sources_service.list_source_capabilities(env)
    cap = _codex_cap(result)
    assert cap is not None
    assert cap.enabled is True
    assert cap.available is False


def test_codex_available_false_when_no_auth(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    env = {"FATTY_LLM_PROVIDER": "codex", "CODEX_HOME": str(codex_home)}
    with patch("app.services.sources.shutil.which", side_effect=_which):
        result = sources_service.list_source_capabilities(env)
    cap = _codex_cap(result)
    assert cap is not None
    assert cap.enabled is True
    assert cap.available is False


def test_codex_available_true_with_fatty_api_key(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    env = {
        "FATTY_LLM_PROVIDER": "codex",
        "CODEX_HOME": str(codex_home),
        "FATTY_LLM_API_KEY": "codex-child-key-must-not-leak",
    }
    with patch("app.services.sources.shutil.which", side_effect=_which):
        result = sources_service.list_source_capabilities(env)
    cap = _codex_cap(result)
    assert cap is not None
    assert cap.enabled is True
    assert cap.available is True


def test_codex_available_true_not_selected(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    env = {"FATTY_LLM_PROVIDER": "fake", "CODEX_HOME": str(codex_home)}
    with patch("app.services.sources.shutil.which", side_effect=_which):
        result = sources_service.list_source_capabilities(env)
    cap = _codex_cap(result)
    assert cap is not None
    assert cap.enabled is False
    assert cap.available is True


def test_codex_ignores_generic_api_key_when_not_selected(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    env = {
        "FATTY_LLM_PROVIDER": "anthropic",
        "FATTY_LLM_API_KEY": "anthropic-key-must-not-count-as-codex-auth",
        "FATTY_LLM_MODEL": "claude-3-5-haiku-20241022",
        "CODEX_HOME": str(codex_home),
    }
    with patch("app.services.sources.shutil.which", side_effect=_which):
        result = sources_service.list_source_capabilities(env)
    cap = _codex_cap(result)
    assert cap is not None
    assert cap.enabled is False
    assert cap.available is False


def test_no_secret_or_path_in_codex_descriptor(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    codex_home = tmp_path / "codex-secret-home"
    codex_home.mkdir()
    auth = {
        "token": "SECRET-TOKEN-MUST-NOT-LEAK",
        "account": "user@example.com",
        "raw_cli_output": "not surfaced",
    }
    (codex_home / "auth.json").write_text(json.dumps(auth), encoding="utf-8")

    env = {
        "FATTY_LLM_PROVIDER": "codex",
        "CODEX_HOME": str(codex_home),
        "FATTY_LLM_API_KEY": "codex-child-key-must-not-leak",
    }
    with patch("app.services.sources.shutil.which", side_effect=_which):
        result = sources_service.list_source_capabilities(env)

    cap = _codex_cap(result)
    assert cap is not None
    cap_dict = cap.model_dump()
    serialized = json.dumps(cap_dict)
    log_text = caplog.text

    forbidden_values = {
        "SECRET-TOKEN-MUST-NOT-LEAK",
        "user@example.com",
        "not surfaced",
        "codex-child-key-must-not-leak",
        str(codex_home),
        "auth.json",
    }
    for value in forbidden_values:
        assert value not in serialized
        assert value not in log_text

    forbidden_field_substrings = {
        "token",
        "credential",
        "secret",
        "account",
        "identity",
        "session",
        "path",
        "file",
        "output",
        "key",
    }
    for field_name in cap_dict:
        assert not any(s in field_name.lower() for s in forbidden_field_substrings), (
            f"Capability field {field_name!r} looks secret-bearing"
        )


def test_healthz_sources_includes_codex_descriptor(client: TestClient) -> None:
    with patch("app.services.sources.shutil.which", return_value=None):
        response = client.get("/healthz/sources")

    assert response.status_code == 200
    sources = {s["id"]: s for s in response.json()["sources"]}

    assert "codex" in sources
    codex = sources["codex"]
    assert codex["source_type"] == "llm_provider"
    assert codex["kinds"] == ["estimation"]
    assert isinstance(codex["enabled"], bool)
    assert isinstance(codex["available"], bool)

    for forbidden_field in (
        "token",
        "key",
        "credential",
        "session",
        "account",
        "identity",
        "path",
        "file",
        "output",
    ):
        assert forbidden_field not in codex


def test_healthz_sources_codex_disabled_by_default(client: TestClient) -> None:
    with patch("app.services.sources.shutil.which", return_value=None):
        response = client.get("/healthz/sources")

    sources = {s["id"]: s for s in response.json()["sources"]}
    assert sources["codex"]["enabled"] is False

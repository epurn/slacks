"""Diagnostics tests for the claude_code provider capability descriptor (FTY-088).

Asserts the /healthz/sources claude_code entry:
  - correct enabled/available booleans across present/absent CLI and session;
  - no token, session content, account identity, or raw CLI output in the response;
  - no live claude invocation in any code path tested here.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.schemas.sources import SourceCapability, SourcesStatus
from app.services import sources as sources_service
from app.services.sources import _probe_claude_code, _session_present

# ---------------------------------------------------------------------------
# _session_present unit tests
# ---------------------------------------------------------------------------


def test_session_present_nonexistent_dir(tmp_path: Path) -> None:
    assert _session_present(str(tmp_path / "does-not-exist")) is False


def test_session_present_empty_dir(tmp_path: Path) -> None:
    d = tmp_path / "claude"
    d.mkdir()
    assert _session_present(str(d)) is False


def test_session_present_non_json_file(tmp_path: Path) -> None:
    d = tmp_path / "claude"
    d.mkdir()
    (d / "README.txt").write_text("not a session")
    assert _session_present(str(d)) is False


def test_session_present_json_file(tmp_path: Path) -> None:
    d = tmp_path / "claude"
    d.mkdir()
    # File presence is the check; content is never read.
    (d / "credentials.json").write_text("{}")
    assert _session_present(str(d)) is True


def test_session_present_does_not_read_file_content(tmp_path: Path) -> None:
    """Confirm that the session check never opens or reads the credential file."""
    d = tmp_path / "claude"
    d.mkdir()
    creds = d / "credentials.json"
    creds.write_text('{"token": "super-secret-should-never-be-read"}')

    with patch("builtins.open", side_effect=AssertionError("session check must not read files")):
        result = _session_present(str(d))

    # It returns True (file present) without reading it.
    assert result is True


# ---------------------------------------------------------------------------
# _probe_claude_code unit tests
# ---------------------------------------------------------------------------


def test_probe_binary_absent() -> None:
    with patch("app.services.sources.shutil.which", return_value=None):
        binary, session = _probe_claude_code({})
    assert binary is False
    assert session is False


def test_probe_binary_present_no_session(tmp_path: Path) -> None:
    d = tmp_path / "claude"
    d.mkdir()
    env = {"CLAUDE_CONFIG_DIR": str(d)}
    with patch("app.services.sources.shutil.which", return_value="/usr/bin/claude"):
        binary, session = _probe_claude_code(env)
    assert binary is True
    assert session is False


def test_probe_binary_present_with_session(tmp_path: Path) -> None:
    d = tmp_path / "claude"
    d.mkdir()
    (d / "credentials.json").write_text("{}")
    env = {"CLAUDE_CONFIG_DIR": str(d)}
    with patch("app.services.sources.shutil.which", return_value="/usr/bin/claude"):
        binary, session = _probe_claude_code(env)
    assert binary is True
    assert session is True


def test_probe_default_config_dir_when_env_unset(tmp_path: Path) -> None:
    """CLAUDE_CONFIG_DIR absent in environ → falls back to ~/.claude resolution."""
    with (
        patch("app.services.sources.shutil.which", return_value="/usr/bin/claude"),
        patch("app.services.sources.os.path.expanduser", return_value=str(tmp_path / "no-session")),
    ):
        binary, session = _probe_claude_code({})
    assert binary is True
    assert session is False  # dir doesn't exist → no session


# ---------------------------------------------------------------------------
# list_source_capabilities — claude_code descriptor tests
# ---------------------------------------------------------------------------


def _claude_code_cap(result: SourcesStatus) -> SourceCapability | None:
    for cap in result.sources:
        if cap.id == "claude_code":
            return cap
    return None


def test_claude_code_descriptor_present() -> None:
    """The claude_code capability always appears in the sources list."""
    with patch("app.services.sources.shutil.which", return_value=None):
        result = sources_service.list_source_capabilities({})
    assert _claude_code_cap(result) is not None


def test_claude_code_disabled_when_not_selected() -> None:
    env = {"FATTY_LLM_PROVIDER": "fake"}
    with patch("app.services.sources.shutil.which", return_value=None):
        result = sources_service.list_source_capabilities(env)
    cap = _claude_code_cap(result)
    assert cap is not None
    assert cap.enabled is False


def test_claude_code_enabled_when_selected(tmp_path: Path) -> None:
    d = tmp_path / "claude"
    d.mkdir()
    (d / "credentials.json").write_text("{}")
    env = {"FATTY_LLM_PROVIDER": "claude_code", "CLAUDE_CONFIG_DIR": str(d)}
    with patch("app.services.sources.shutil.which", return_value="/usr/bin/claude"):
        result = sources_service.list_source_capabilities(env)
    cap = _claude_code_cap(result)
    assert cap is not None
    assert cap.enabled is True
    assert cap.available is True


def test_claude_code_available_false_when_binary_absent(tmp_path: Path) -> None:
    env = {"FATTY_LLM_PROVIDER": "claude_code", "CLAUDE_CONFIG_DIR": str(tmp_path)}
    with patch("app.services.sources.shutil.which", return_value=None):
        result = sources_service.list_source_capabilities(env)
    cap = _claude_code_cap(result)
    assert cap is not None
    assert cap.enabled is True
    assert cap.available is False


def test_claude_code_available_false_when_no_session(tmp_path: Path) -> None:
    d = tmp_path / "claude"
    d.mkdir()
    # No JSON files = no session
    env = {"FATTY_LLM_PROVIDER": "claude_code", "CLAUDE_CONFIG_DIR": str(d)}
    with patch("app.services.sources.shutil.which", return_value="/usr/bin/claude"):
        result = sources_service.list_source_capabilities(env)
    cap = _claude_code_cap(result)
    assert cap is not None
    assert cap.enabled is True
    assert cap.available is False


def test_claude_code_available_true_not_selected(tmp_path: Path) -> None:
    """Binary+session present but different provider selected: available=True, enabled=False."""
    d = tmp_path / "claude"
    d.mkdir()
    (d / "credentials.json").write_text("{}")
    env = {"FATTY_LLM_PROVIDER": "fake", "CLAUDE_CONFIG_DIR": str(d)}
    with patch("app.services.sources.shutil.which", return_value="/usr/bin/claude"):
        result = sources_service.list_source_capabilities(env)
    cap = _claude_code_cap(result)
    assert cap is not None
    assert cap.enabled is False
    assert cap.available is True


# ---------------------------------------------------------------------------
# Security: no secrets / identity in the descriptor
# ---------------------------------------------------------------------------


def test_no_secret_in_claude_code_descriptor(tmp_path: Path) -> None:
    """The claude_code capability must carry booleans only — no token, session,
    account identity, or raw CLI output (FTY-088 security requirement)."""
    d = tmp_path / "claude"
    d.mkdir()
    # Write a credential file with a clearly identifiable secret payload.
    creds = {"token": "SECRET-TOKEN-MUST-NOT-LEAK", "account": "user@example.com"}
    (d / "credentials.json").write_text(json.dumps(creds))

    env = {"FATTY_LLM_PROVIDER": "claude_code", "CLAUDE_CONFIG_DIR": str(d)}
    with patch("app.services.sources.shutil.which", return_value="/usr/bin/claude"):
        result = sources_service.list_source_capabilities(env)

    cap = _claude_code_cap(result)
    assert cap is not None

    cap_dict = cap.model_dump()
    serialized = json.dumps(cap_dict)

    # The credential values must never appear in the serialized descriptor.
    assert "SECRET-TOKEN-MUST-NOT-LEAK" not in serialized
    assert "user@example.com" not in serialized

    # Field names must not suggest secret carriage.
    forbidden_field_substrings = {"token", "credential", "secret", "account", "identity", "session"}
    for field_name in cap_dict:
        assert not any(s in field_name.lower() for s in forbidden_field_substrings), (
            f"Capability field {field_name!r} looks secret-bearing"
        )


# ---------------------------------------------------------------------------
# HTTP-level integration: claude_code appears in /healthz/sources response
# ---------------------------------------------------------------------------


def test_healthz_sources_includes_claude_code_descriptor(client: TestClient) -> None:
    """The HTTP endpoint always includes the claude_code descriptor with correct shape."""
    with patch("app.services.sources.shutil.which", return_value=None):
        response = client.get("/healthz/sources")

    assert response.status_code == 200
    sources = {s["id"]: s for s in response.json()["sources"]}

    assert "claude_code" in sources
    cc = sources["claude_code"]
    assert cc["source_type"] == "llm_provider"
    assert cc["kinds"] == ["estimation"]
    assert isinstance(cc["enabled"], bool)
    assert isinstance(cc["available"], bool)

    # No secret-bearing fields in the HTTP response.
    assert "token" not in cc
    assert "key" not in cc
    assert "credential" not in cc
    assert "session" not in cc
    assert "account" not in cc
    assert "identity" not in cc


def test_healthz_sources_claude_code_disabled_by_default(client: TestClient) -> None:
    """Default test env uses fake provider: claude_code.enabled must be False."""
    with patch("app.services.sources.shutil.which", return_value=None):
        response = client.get("/healthz/sources")

    sources = {s["id"]: s for s in response.json()["sources"]}
    assert sources["claude_code"]["enabled"] is False

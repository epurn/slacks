"""Unit tests for the local simulator-readiness smoke (FTY-250).

Cover the pure logic the operator command relies on: ``.env`` parsing, API-port
resolution, the simulator connect URL, secret redaction, Alembic-drift detection,
backend image coherence, and the ``/healthz/sources`` summary. The Docker/HTTP
orchestration is intentionally not exercised here — it needs a live stack — but
every value the report *prints* flows through a function verified below.
"""

from __future__ import annotations

import pytest

from app.llm.config import ENV_PREFIX as LLM_ENV_PREFIX
from app.ops import sim_readiness as sr

# --------------------------------------------------------------------------- #
# .env parsing + API port + simulator URL
# --------------------------------------------------------------------------- #


def test_parse_env_skips_comments_and_blanks_and_splits_on_first_equals() -> None:
    env = sr.parse_env(
        "\n".join(
            [
                "# a comment",
                "",
                "API_PORT=18000",
                "SLACKS_DATABASE_URL=postgresql://slacks:slacks@postgres:5432/slacks",
                "   # indented comment",
                "SLACKS_LLM_PROVIDER = claude_code ",
            ]
        )
    )
    assert env["API_PORT"] == "18000"
    assert env["SLACKS_LLM_PROVIDER"] == "claude_code"
    # First-'=' split keeps the DSN (which itself contains no '=') intact.
    assert env["SLACKS_DATABASE_URL"].endswith("@postgres:5432/slacks")
    assert "# a comment" not in env


def test_parse_api_port_defaults_when_absent() -> None:
    assert sr.parse_api_port({}) == sr.DEFAULT_API_PORT == 8000


def test_parse_api_port_reads_configured_value() -> None:
    assert sr.parse_api_port({"API_PORT": "18000"}) == 18000


def test_parse_api_port_rejects_non_integer() -> None:
    with pytest.raises(ValueError, match="not an integer"):
        sr.parse_api_port({"API_PORT": "eighteen-thousand"})


def test_parse_api_port_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="out of range"):
        sr.parse_api_port({"API_PORT": "70000"})


def test_simulator_url_uses_configured_port_not_the_mobile_fallback() -> None:
    # The 2026-07-05 drift: .env published API_PORT=18000 while the mobile
    # fallback is localhost:8000. The smoke must print the real port.
    assert sr.simulator_url(18000) == "http://localhost:18000"
    assert sr.simulator_url(8000) == "http://localhost:8000"


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "key",
    [
        "SLACKS_AUTH_SECRET",
        "POSTGRES_PASSWORD",
        "SLACKS_LLM_API_KEY",
        "SLACKS_SEARCH_API_KEY",
        "SOME_TOKEN",
        "CLAUDE_SESSION",
    ],
)
def test_is_secret_env_key_flags_secrets(key: str) -> None:
    assert sr.is_secret_env_key(key) is True


@pytest.mark.parametrize(
    "key",
    ["API_PORT", "POSTGRES_PORT", "SLACKS_LLM_PROVIDER", "SLACKS_ENVIRONMENT"],
)
def test_is_secret_env_key_allows_non_secrets(key: str) -> None:
    assert sr.is_secret_env_key(key) is False


def test_redact_env_value_masks_secret_values() -> None:
    assert sr.redact_env_value("SLACKS_AUTH_SECRET", "hunter2") == sr._REDACTED
    assert sr.redact_env_value("POSTGRES_PASSWORD", "slacks") == sr._REDACTED


def test_redact_env_value_passes_non_secret_values() -> None:
    assert sr.redact_env_value("API_PORT", "18000") == "18000"


def test_redact_env_value_leaves_empty_unchanged() -> None:
    assert sr.redact_env_value("SLACKS_AUTH_SECRET", "") == ""


def test_reported_env_curates_and_redacts() -> None:
    # The LLM provider key stays on the FTY-334-owned ``ENV_PREFIX`` until that
    # story flips it; derive it here so the assertion tracks the real key.
    llm_provider_key = f"{LLM_ENV_PREFIX}PROVIDER"
    env = {
        llm_provider_key: "claude_code",
        "SLACKS_AUTH_SECRET": "hunter2",
        "SLACKS_DATABASE_URL": "postgresql://slacks:slacks@postgres:5432/slacks",
    }
    pairs = dict(sr.reported_env(env))
    assert pairs[llm_provider_key] == "claude_code"
    # Secrets and DSNs are never surfaced by the curated allowlist.
    assert "SLACKS_AUTH_SECRET" not in pairs
    assert "SLACKS_DATABASE_URL" not in pairs


# --------------------------------------------------------------------------- #
# Alembic drift
# --------------------------------------------------------------------------- #


def test_alembic_status_at_head() -> None:
    status = sr.AlembicStatus(db_version="0018", code_head="0018")
    assert status.at_head is True
    assert "head 0018" in status.message


def test_alembic_status_reports_drift_with_both_versions() -> None:
    status = sr.AlembicStatus(db_version="0017", code_head="0018")
    assert status.at_head is False
    assert "0017" in status.message
    assert "0018" in status.message
    assert "DRIFT" in status.message


def test_alembic_status_handles_unreadable_db_version() -> None:
    status = sr.AlembicStatus(db_version=None, code_head="0018")
    assert status.at_head is False
    assert "could not be read" in status.message


def test_code_head_revision_matches_the_shipped_head() -> None:
    # Guards that the smoke reads the head from the migration scripts, and pins
    # the current head the story is calibrated against.
    assert sr.code_head_revision() == "0020"


# --------------------------------------------------------------------------- #
# Image coherence
# --------------------------------------------------------------------------- #


def test_image_coherence_all_same_is_coherent() -> None:
    coherence = sr.ImageCoherence(
        {"api": "sha256:abc", "worker": "sha256:abc", "migrate": "sha256:abc"}
    )
    assert coherence.coherent is True
    assert "coherent" in coherence.message


def test_image_coherence_divergent_ids_is_drift() -> None:
    coherence = sr.ImageCoherence(
        {"api": "sha256:new", "worker": "sha256:old", "migrate": "sha256:new"}
    )
    assert coherence.coherent is False
    assert "DRIFT" in coherence.message


def test_image_coherence_unbuilt_service_is_not_coherent() -> None:
    coherence = sr.ImageCoherence({"api": "sha256:abc", "worker": None, "migrate": "sha256:abc"})
    assert coherence.coherent is False
    assert "not built" in coherence.message
    assert "worker" in coherence.message


# --------------------------------------------------------------------------- #
# Worker health
# --------------------------------------------------------------------------- #


def test_worker_health_pong_is_healthy() -> None:
    health = sr.worker_health_from_ping(0, "-> celery@host: OK\n        pong\n", "")
    assert health.healthy is True
    assert "responding" in health.message


def test_worker_health_no_reply_is_unhealthy() -> None:
    # Celery exits non-zero with "Error: No nodes replied..." when no worker is up.
    health = sr.worker_health_from_ping(69, "", "Error: No nodes replied within time constraint.")
    assert health.healthy is False
    assert "No nodes replied" in health.detail
    assert "worker not responding" in health.message


def test_worker_health_container_down_is_unhealthy() -> None:
    # `docker compose exec` against a stopped service fails before celery runs.
    health = sr.worker_health_from_ping(1, "", 'service "worker" is not running')
    assert health.healthy is False
    assert "not responding" in health.message


def test_worker_health_zero_exit_without_pong_is_unhealthy() -> None:
    # Defensive: a clean exit that never printed a pong is still not a live worker.
    health = sr.worker_health_from_ping(0, "", "")
    assert health.healthy is False
    assert health.detail == "no response"


# --------------------------------------------------------------------------- #
# Sources summary
# --------------------------------------------------------------------------- #


def test_summarize_sources_formats_capabilities() -> None:
    payload = {
        "sources": [
            {
                "id": "claude_code",
                "source_type": "llm_provider",
                "kinds": [],
                "enabled": True,
                "available": False,
            },
            {
                "id": "off",
                "source_type": "product_db",
                "kinds": ["barcode"],
                "enabled": True,
                "available": True,
            },
        ]
    }
    lines = sr.summarize_sources(payload)
    assert any("claude_code [llm_provider] enabled=True available=False" in line for line in lines)
    assert any("off [product_db] enabled=True available=True" in line for line in lines)


def test_summarize_sources_redacts_a_secret_looking_field() -> None:
    payload = {"sources": [{"id": "x", "source_type": "t", "api_key": "leak"}]}
    lines = sr.summarize_sources(payload)
    assert sr._REDACTED in lines[0]
    assert "leak" not in lines[0]


def test_summarize_sources_handles_unexpected_shape() -> None:
    assert sr.summarize_sources(["not", "a", "mapping"]) == [
        "(unexpected /healthz/sources payload)"
    ]
    assert sr.summarize_sources({"sources": []}) == ["(no evidence sources reported)"]

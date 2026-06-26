"""Bearer token tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.security.tokens import InvalidToken, mint_token, parse_token

SECRET = "test-secret"  # noqa: S105 (test signing key, not a real credential)


def test_round_trip_returns_subject() -> None:
    user_id = uuid.uuid4()
    token = mint_token(user_id, SECRET, ttl_seconds=3600)

    assert parse_token(token, SECRET) == user_id


def test_tampered_signature_is_rejected() -> None:
    token = mint_token(uuid.uuid4(), SECRET, ttl_seconds=3600)
    payload, _signature = token.split(".")
    forged = f"{payload}.{'A' * 10}"

    with pytest.raises(InvalidToken):
        parse_token(forged, SECRET)


def test_wrong_secret_is_rejected() -> None:
    token = mint_token(uuid.uuid4(), SECRET, ttl_seconds=3600)

    with pytest.raises(InvalidToken):
        parse_token(token, "different-secret")


def test_expired_token_is_rejected() -> None:
    issued = datetime.now(UTC) - timedelta(hours=2)
    token = mint_token(uuid.uuid4(), SECRET, ttl_seconds=3600, now=issued)

    with pytest.raises(InvalidToken):
        parse_token(token, SECRET)


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(InvalidToken):
        parse_token("not-a-token", SECRET)

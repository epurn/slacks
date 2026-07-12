"""Auth API integration tests: register and login."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.services.auth as _auth_module


def test_register_returns_user_and_token(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/register",
        json={"email": "Alice@Example.com", "password": "super-secret-pw"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["id"]
    assert body["token"]["token_type"] == "bearer"  # noqa: S105 (token type, not a secret)
    assert body["token"]["access_token"]
    assert body["token"]["expires_in"] > 0
    # The password and its hash must never appear in the response.
    assert "super-secret-pw" not in resp.text
    assert "password" not in body["user"]


def test_register_duplicate_email_conflicts_case_insensitive(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": "first-password"},
    )
    resp = client.post(
        "/api/auth/register",
        json={"email": "BOB@example.com", "password": "second-password"},
    )

    assert resp.status_code == 409


def test_register_rejects_weak_and_invalid_input(client: TestClient) -> None:
    short_pw = client.post(
        "/api/auth/register",
        json={"email": "carol@example.com", "password": "short"},
    )
    bad_email = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "long-enough-password"},
    )

    assert short_pw.status_code == 422
    assert bad_email.status_code == 422


def test_login_succeeds_with_correct_credentials(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={"email": "dave@example.com", "password": "correct-password"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "dave@example.com", "password": "correct-password"},
    )

    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_login_wrong_password_is_unauthorized(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        json={"email": "erin@example.com", "password": "correct-password"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "erin@example.com", "password": "wrong-password"},
    )

    assert resp.status_code == 401


def test_login_unknown_email_is_unauthorized(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "any-password-here"},
    )

    # Same generic 401 as a wrong password: no account-existence oracle.
    assert resp.status_code == 401


def test_protected_route_non_ascii_token_is_unauthorized(client: TestClient) -> None:
    """A non-ASCII bearer token fails closed as 401, never an unhandled 500.

    HTTP header values reach Starlette latin-1-decoded, so a client can place a
    non-ASCII byte in the ``Authorization`` value. That value used to crash the
    token verifier (UnicodeEncodeError / TypeError) and surface as a 500 with a
    stack trace; deps.py catches only InvalidToken. The verifier now fails
    closed, so the request maps to the generic 401.
    """

    # Latin-1-encodable so it survives the HTTP header transport, as a real
    # client's header would.
    resp = client.get(
        f"/api/users/{uuid.uuid4()}/profile",
        headers={"Authorization": "Bearer é.x".encode("latin-1")},
    )

    assert resp.status_code == 401
    # Generic credential message only: no stack trace or internal detail leaks.
    assert resp.json() == {"detail": "missing or invalid credentials"}
    assert "Traceback" not in resp.text
    assert "UnicodeEncodeError" not in resp.text


def test_concurrent_register_race_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent same-email registrations must yield 409, not 500.

    Simulates the race: the first request commits successfully, then the
    existence check is patched to return None so the second request bypasses
    the sequential-duplicate guard and reaches the commit, where the unique
    index (uq_auth_provider_identifier) fires.  The IntegrityError must be
    caught, rolled back, and surfaced as 409 Conflict.
    """

    r1 = client.post(
        "/api/auth/register",
        json={"email": "race@example.com", "password": "first-password"},
    )
    assert r1.status_code == 201

    # Bypass the sequential check: both concurrent callers see no existing row.
    monkeypatch.setattr(_auth_module, "_find_local_identity", lambda *_: None)

    r2 = client.post(
        "/api/auth/register",
        json={"email": "race@example.com", "password": "second-password"},
    )
    assert r2.status_code == 409

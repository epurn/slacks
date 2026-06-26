"""Auth API integration tests: register and login."""

from __future__ import annotations

from fastapi.testclient import TestClient


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

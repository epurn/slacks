"""Password hashing tests."""

from __future__ import annotations

from app.security.passwords import hash_password, verify_password


def test_hash_is_not_plaintext_and_is_self_describing() -> None:
    encoded = hash_password("correct horse battery staple")

    assert "correct horse" not in encoded
    assert encoded.startswith("scrypt$")
    assert len(encoded.split("$")) == 6


def test_verify_accepts_correct_password() -> None:
    encoded = hash_password("s3cret-passw0rd")

    assert verify_password("s3cret-passw0rd", encoded) is True


def test_verify_rejects_wrong_password() -> None:
    encoded = hash_password("s3cret-passw0rd")

    assert verify_password("not-the-password", encoded) is False


def test_hash_is_salted_unique_per_call() -> None:
    first = hash_password("same-input")
    second = hash_password("same-input")

    assert first != second
    assert verify_password("same-input", first)
    assert verify_password("same-input", second)


def test_verify_fails_closed_on_malformed_hash() -> None:
    # A corrupted/unsupported encoding must read as an auth failure, not crash.
    assert verify_password("password", "not-a-valid-hash") is False
    assert verify_password("password", "bcrypt$1$2$3$4$5") is False

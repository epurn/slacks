"""Stateless bearer tokens for the local auth path.

A token is an HMAC-SHA256-signed claim ``{"sub": <user id>, "iat", "exp"}``,
encoded ``<payload_b64url>.<signature_b64url>``. The signing secret is read from
the environment (``FATTY_AUTH_SECRET``) and never embedded in the token or
logged. Tokens are stateless (no session table) which keeps this slice minimal;
a future hosted-auth story can introduce server-side sessions/revocation.

Trust boundary: a token is untrusted input. :func:`parse_token` verifies the
signature in constant time and enforces expiry before returning the subject, and
raises :class:`InvalidToken` for anything malformed, tampered, or expired so the
caller fails closed.
"""

from __future__ import annotations

import hmac
import json
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from hashlib import sha256


class InvalidToken(Exception):
    """Raised when a bearer token is malformed, tampered with, or expired."""


def mint_token(
    user_id: uuid.UUID, secret: str, ttl_seconds: int, *, now: datetime | None = None
) -> str:
    """Mint a signed bearer token for ``user_id`` valid for ``ttl_seconds``."""

    issued = now or datetime.now(UTC)
    issued_ts = int(issued.timestamp())
    payload = {"sub": str(user_id), "iat": issued_ts, "exp": issued_ts + ttl_seconds}
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(payload_b64, secret)
    return f"{payload_b64}.{signature}"


def parse_token(token: str, secret: str, *, now: datetime | None = None) -> uuid.UUID:
    """Verify ``token`` and return its subject user id.

    Raises :class:`InvalidToken` if the structure, signature, claims, or expiry
    are invalid.
    """

    try:
        payload_b64, signature = token.split(".")
    except ValueError as exc:
        raise InvalidToken("malformed token") from exc

    expected_sig = _sign(payload_b64, secret)
    # Constant-time comparison: a forged token cannot be distinguished by timing.
    if not hmac.compare_digest(signature, expected_sig):
        raise InvalidToken("bad signature")

    try:
        payload = json.loads(_b64decode(payload_b64))
        subject = str(payload["sub"])
        expires_at = int(payload["exp"])
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidToken("malformed payload") from exc

    current = now or datetime.now(UTC)
    if int(current.timestamp()) >= expires_at:
        raise InvalidToken("expired token")

    try:
        return uuid.UUID(subject)
    except ValueError as exc:
        raise InvalidToken("invalid subject") from exc


def _sign(payload_b64: str, secret: str) -> str:
    """HMAC-SHA256 sign the encoded payload and return a base64url signature."""

    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), sha256).digest()
    return _b64encode(digest)


def _b64encode(raw: bytes) -> str:
    """URL-safe base64 without padding (compact, URL/header friendly)."""

    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(encoded: str) -> bytes:
    """Inverse of :func:`_b64encode`, restoring stripped padding."""

    padding = "=" * (-len(encoded) % 4)
    return urlsafe_b64decode(encoded + padding)

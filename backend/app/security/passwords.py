"""Password hashing for the local auth path.

Uses :func:`hashlib.scrypt`, a memory-hard password hash from the standard
library, so the project gets a strong, salted, tunable hash without taking on a
third-party crypto dependency. Each hash is encoded as a self-describing string
that carries the cost parameters and a per-password random salt, so stored
hashes remain verifiable if the defaults are tuned later.

Security notes:

- Plaintext passwords are never stored, returned, or logged; only the encoded
  hash leaves this module.
- Verification is constant-time (:func:`hmac.compare_digest`) to avoid leaking
  match information through timing.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode

#: scrypt cost parameters. ``N`` (CPU/memory cost) must be a power of two; these
#: values follow common interactive-login guidance and bound memory to ~16 MiB.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_DKLEN = 32
#: OpenSSL refuses scrypt unless ``maxmem`` covers ``128 * N * r * p`` bytes;
#: give a little headroom so parameter bumps do not immediately fail.
_MAXMEM = 128 * _SCRYPT_N * _SCRYPT_R * _SCRYPT_P * 2

_SCHEME = "scrypt"


def hash_password(password: str) -> str:
    """Return a self-describing scrypt hash of ``password``.

    Format: ``scrypt$<N>$<r>$<p>$<salt_b64>$<hash_b64>``. A fresh random salt is
    generated per call, so hashing the same password twice yields different
    encodings.
    """

    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _derive(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return "$".join(
        [
            _SCHEME,
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            b64encode(salt).decode("ascii"),
            b64encode(derived).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    """Return ``True`` iff ``password`` matches the ``encoded`` scrypt hash.

    Returns ``False`` for any malformed or unsupported encoding rather than
    raising, so a corrupted stored hash fails closed as an authentication
    failure instead of a server error.
    """

    try:
        scheme, n_raw, r_raw, p_raw, salt_b64, hash_b64 = encoded.split("$")
        if scheme != _SCHEME:
            return False
        n, r, p = int(n_raw), int(r_raw), int(p_raw)
        salt = b64decode(salt_b64)
        expected = b64decode(hash_b64)
    except (ValueError, TypeError):
        return False

    candidate = _derive(password, salt, n, r, p, dklen=len(expected))
    return hmac.compare_digest(candidate, expected)


def _derive(password: str, salt: bytes, n: int, r: int, p: int, *, dklen: int = _DKLEN) -> bytes:
    """Run scrypt with the given parameters and return the derived key bytes."""

    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=dklen,
        maxmem=_MAXMEM,
    )

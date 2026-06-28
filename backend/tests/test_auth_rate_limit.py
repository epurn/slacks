"""Rate-limit tests for the auth endpoints (FTY-118).

Covers:
- Per-IP throttle on /login and /register
- Per-account throttle on /login from rotating IPs (via X-Forwarded-For)
- Legitimate cadence below the threshold is never throttled
- Shared counter: two app instances sharing one seam enforce one combined limit
- IP-spoof rejection: X-Forwarded-For is ignored unless trusted_proxy is on, and
  even then the rightmost (proxy-appended) hop is keyed so a forged leftmost
  value cannot mint fresh per-IP keys
- Fail-open: a limiter seam that raises still allows the request (no 500)
- The production ``RedisRateLimiter.check`` shipping path against a faithful
  in-memory Redis double (no live Redis, no unapproved ``fakeredis`` dep): the
  INCR/TTL pipeline, the ``ttl == -1`` first-hit window pin, ``count <= limit``,
  retry_after derived from the real TTL, and window *reset* after expiry
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_db_engine
from app.main import create_app
from app.security.rate_limit import (
    InMemoryRateLimiter,
    RateLimitDecision,
    RateLimiter,
    RedisRateLimiter,
)
from app.settings import Settings
from tests.conftest import RecordingEnqueuer, upgrade

# A valid login password that passes the 8-char schema minimum.
_PW = "any-password"

_LOW_LIMIT_SETTINGS = Settings(
    environment="test",
    log_level="WARNING",
    rate_limit_login_ip_max=2,
    rate_limit_login_ip_window=60,
    rate_limit_login_account_max=2,
    rate_limit_login_account_window=60,
    rate_limit_register_ip_max=2,
    rate_limit_register_ip_window=60,
)

_TRUSTED_PROXY_SETTINGS = Settings(
    environment="test",
    log_level="WARNING",
    rate_limit_login_ip_max=100,  # high so per-IP limit never fires in account tests
    rate_limit_login_ip_window=60,
    rate_limit_login_account_max=2,
    rate_limit_login_account_window=60,
    rate_limit_register_ip_max=100,
    rate_limit_register_ip_window=60,
    rate_limit_trusted_proxy=True,
)

_PROXY_ON_LOW_IP_SETTINGS = Settings(
    environment="test",
    log_level="WARNING",
    rate_limit_login_ip_max=2,
    rate_limit_login_ip_window=60,
    rate_limit_login_account_max=100,  # high so the account limit never fires here
    rate_limit_login_account_window=60,
    rate_limit_register_ip_max=100,
    rate_limit_register_ip_window=60,
    rate_limit_trusted_proxy=True,
)

_PROXY_OFF_SETTINGS = Settings(
    environment="test",
    log_level="WARNING",
    rate_limit_login_ip_max=2,
    rate_limit_login_ip_window=60,
    rate_limit_login_account_max=100,  # high so account limit never fires in IP tests
    rate_limit_login_account_window=60,
    rate_limit_register_ip_max=100,
    rate_limit_register_ip_window=60,
    rate_limit_trusted_proxy=False,
)


@pytest.fixture
def low_limit_db(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'rl_test.db'}")
    upgrade(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _make_client(
    engine: Engine,
    settings: Settings,
    rate_limiter: RateLimiter | None = None,
) -> TestClient:
    """Build a TestClient with the given settings and rate-limiter seam."""
    app = create_app(settings=settings, engine=engine)
    app.state.estimation_enqueuer = RecordingEnqueuer()
    app.state.rate_limiter = rate_limiter or InMemoryRateLimiter()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Per-IP throttle: /login
# ---------------------------------------------------------------------------


def test_login_per_ip_throttled(low_limit_db: Engine) -> None:
    """Exceeding the per-IP login limit returns 429 with a Retry-After header."""
    client = _make_client(low_limit_db, _LOW_LIMIT_SETTINGS)

    # First two requests are under the limit — normal 200/401 responses
    for _ in range(2):
        resp = client.post("/api/auth/login", json={"email": "x@example.com", "password": _PW})
        assert resp.status_code != 429

    # Third attempt → throttled
    resp = client.post("/api/auth/login", json={"email": "x@example.com", "password": _PW})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


# ---------------------------------------------------------------------------
# Per-account throttle: /login from rotating IPs
# ---------------------------------------------------------------------------


def test_login_per_account_throttled_rotating_ips(low_limit_db: Engine) -> None:
    """The per-account limit fires even when each request comes from a different IP."""
    client = _make_client(low_limit_db, _TRUSTED_PROXY_SETTINGS)

    # Register target account
    client.post(
        "/api/auth/register",
        json={"email": "victim@example.com", "password": "password-ok-1"},
    )

    # Two attempts from distinct IPs — both under the account limit
    for i in range(2):
        resp = client.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.0.0.{i + 1}"},
        )
        assert resp.status_code != 429

    # Third attempt from a fresh IP → per-account limit fires
    resp = client.post(
        "/api/auth/login",
        json={"email": "victim@example.com", "password": "wrong-password"},
        headers={"X-Forwarded-For": "10.0.0.99"},
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


# ---------------------------------------------------------------------------
# Per-IP throttle: /register
# ---------------------------------------------------------------------------


def test_register_per_ip_throttled(low_limit_db: Engine) -> None:
    """Exceeding the per-IP register limit returns 429 with a Retry-After header."""
    client = _make_client(low_limit_db, _LOW_LIMIT_SETTINGS)

    # First two under limit — normal 201 (or 409 for a duplicate)
    for i in range(2):
        resp = client.post(
            "/api/auth/register",
            json={"email": f"u{i}@example.com", "password": "password-ok-1"},
        )
        assert resp.status_code != 429

    # Third attempt → throttled before the insert
    resp = client.post(
        "/api/auth/register",
        json={"email": "u3@example.com", "password": "password-ok-1"},
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


# ---------------------------------------------------------------------------
# Legitimate cadence: never throttled below the threshold
# ---------------------------------------------------------------------------


def test_legitimate_login_cadence_not_throttled(low_limit_db: Engine) -> None:
    """Requests below the threshold always pass through normally."""
    client = _make_client(low_limit_db, _LOW_LIMIT_SETTINGS)
    client.post(
        "/api/auth/register",
        json={"email": "legit@example.com", "password": "password-ok-1"},
    )

    # One successful login followed by one wrong-password 401 — both under the limit
    resp_ok = client.post(
        "/api/auth/login",
        json={"email": "legit@example.com", "password": "password-ok-1"},
    )
    resp_bad = client.post(
        "/api/auth/login",
        json={"email": "legit@example.com", "password": "wrong-password"},
    )
    assert resp_ok.status_code == 200
    assert resp_bad.status_code == 401


# ---------------------------------------------------------------------------
# Shared counter: two "processes" sharing one seam
# ---------------------------------------------------------------------------


def test_shared_counter_across_instances(low_limit_db: Engine) -> None:
    """Two app instances sharing the same seam enforce one combined limit."""
    shared_limiter = InMemoryRateLimiter()

    with (
        _make_client(low_limit_db, _LOW_LIMIT_SETTINGS, shared_limiter) as c1,
        _make_client(low_limit_db, _LOW_LIMIT_SETTINGS, shared_limiter) as c2,
    ):
        # One request through each instance — combined count = 2 (at the limit)
        r1 = c1.post("/api/auth/login", json={"email": "a@b.com", "password": _PW})
        r2 = c2.post("/api/auth/login", json={"email": "a@b.com", "password": _PW})
        assert r1.status_code != 429
        assert r2.status_code != 429

        # Third request through either instance → over the shared limit
        r3 = c1.post("/api/auth/login", json={"email": "a@b.com", "password": _PW})
        assert r3.status_code == 429


# ---------------------------------------------------------------------------
# IP-spoof rejection: X-Forwarded-For ignored when trusted_proxy is off
# ---------------------------------------------------------------------------


def test_ip_spoof_rejected_when_trusted_proxy_off(low_limit_db: Engine) -> None:
    """With trusted_proxy=False, spoofed X-Forwarded-For does not create a fresh key."""
    client = _make_client(low_limit_db, _PROXY_OFF_SETTINGS)

    # Two requests each with a different X-Forwarded-For — but both key on the
    # real peer IP ("testclient"), exhausting the per-IP limit
    for i in range(2):
        resp = client.post(
            "/api/auth/login",
            json={"email": "x@example.com", "password": _PW},
            headers={"X-Forwarded-For": f"1.2.3.{i}"},
        )
        assert resp.status_code != 429

    # Third request with a fresh spoofed IP → real peer is still throttled
    resp = client.post(
        "/api/auth/login",
        json={"email": "x@example.com", "password": _PW},
        headers={"X-Forwarded-For": "1.2.3.99"},
    )
    assert resp.status_code == 429


def test_forwarded_for_honoured_when_trusted_proxy_on(low_limit_db: Engine) -> None:
    """With trusted_proxy=True, each distinct X-Forwarded-For IP gets its own key."""
    client = _make_client(low_limit_db, _TRUSTED_PROXY_SETTINGS)

    # Two requests from distinct IPs (ip_max=100, never trips)
    for i in range(2):
        resp = client.post(
            "/api/auth/login",
            json={"email": "x@example.com", "password": _PW},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
        assert resp.status_code != 429


def test_rightmost_forwarded_for_defeats_leftmost_spoof(low_limit_db: Engine) -> None:
    """A client-forged leftmost X-Forwarded-For cannot mint fresh per-IP keys.

    Proxies append to XFF, so the rightmost entry is the hop the trusted proxy
    wrote (the real peer it observed). The limiter keys on that, so rotating a
    forged *leftmost* value does not evade the per-IP limit.
    """
    client = _make_client(low_limit_db, _PROXY_ON_LOW_IP_SETTINGS)

    # Each request carries an attacker-rotated leftmost value, but the trusted
    # proxy appends the same real peer (203.0.113.7) as the rightmost hop.
    for i in range(2):
        resp = client.post(
            "/api/auth/login",
            json={"email": "x@example.com", "password": _PW},
            headers={"X-Forwarded-For": f"6.6.6.{i}, 203.0.113.7"},
        )
        assert resp.status_code != 429

    # Third request, fresh forged leftmost — still keyed on the rightmost peer.
    resp = client.post(
        "/api/auth/login",
        json={"email": "x@example.com", "password": _PW},
        headers={"X-Forwarded-For": "6.6.6.250, 203.0.113.7"},
    )
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Fail-open: limiter seam raises → request allowed, warning logged
# ---------------------------------------------------------------------------


class _ErrorRateLimiter(RateLimiter):
    """Test double that always raises, simulating a Redis outage."""

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        raise RuntimeError("simulated Redis failure")


def test_fail_open_login_on_limiter_error(low_limit_db: Engine) -> None:
    """When the rate-limiter seam raises, /login still responds normally (fail-open)."""
    warned: list[Any] = []

    # Patch the logger on the auth module before create_app so configure_logging
    # does not clear the capture.  We verify the warning reaches the logger; the
    # JSON formatter then forwards it to stdout (visible in the captured output).
    with patch("app.routers.auth.logger") as mock_log:
        mock_log.warning.side_effect = lambda *a, **kw: warned.append(a[0])
        client = _make_client(low_limit_db, _LOW_LIMIT_SETTINGS, _ErrorRateLimiter())
        resp = client.post(
            "/api/auth/login",
            json={"email": "x@example.com", "password": _PW},
        )

    # Fail-open: 401 for an unknown user, never 500 or 429
    assert resp.status_code not in (500, 429)
    assert any("fail-open" in str(w) for w in warned)


def test_fail_open_register_on_limiter_error(low_limit_db: Engine) -> None:
    """When the rate-limiter seam raises, /register still completes (fail-open)."""
    warned: list[Any] = []

    with patch("app.routers.auth.logger") as mock_log:
        mock_log.warning.side_effect = lambda *a, **kw: warned.append(a[0])
        client = _make_client(low_limit_db, _LOW_LIMIT_SETTINGS, _ErrorRateLimiter())
        resp = client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "password-ok-1"},
        )

    # Fail-open: 201 Created, never 500 or 429
    assert resp.status_code == 201
    assert any("fail-open" in str(w) for w in warned)


# ---------------------------------------------------------------------------
# RedisRateLimiter shipping path — exercised against a faithful Redis double
#
# The integration tests above drive InMemoryRateLimiter, whose semantics differ
# from the production adapter (no TTL/window expiry; retry_after hard-coded to
# the window). These tests exercise the *real* RedisRateLimiter.check against a
# small in-memory stand-in for the redis client — the same approach fakeredis
# would take, but without adding an unapproved dependency. They cover the
# INCR/TTL pipeline, the ``ttl == -1`` first-hit window pin, ``count <= limit``,
# retry_after from the real TTL, and window reset after the window elapses (the
# defining fixed-window behavior, untestable through the in-memory double).
# ---------------------------------------------------------------------------


class _FakePipeline:
    """Queues the incr/ttl ops RedisRateLimiter issues and replays them on execute."""

    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> _FakePipeline:
        self._ops.append(("incr", key))
        return self

    def ttl(self, key: str) -> _FakePipeline:
        self._ops.append(("ttl", key))
        return self

    def execute(self) -> list[int]:
        return [
            self._redis.do_incr(key) if op == "incr" else self._redis.do_ttl(key)
            for op, key in self._ops
        ]


class _FakeRedis:
    """Faithful in-memory stand-in for the redis methods RedisRateLimiter uses.

    Models fixed-window semantics exactly enough to exercise the real check
    path: INCR creates a key with no expiry (TTL reports ``-1``), EXPIRE pins a
    countdown, TTL decays against an injectable clock, and a key is evicted once
    its window elapses (this is what makes window *reset* observable). The clock
    only moves when a test calls :meth:`advance`.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._expire_at: dict[str, int] = {}
        self.now: int = 0

    def _sweep(self) -> None:
        for key in [k for k, exp in self._expire_at.items() if self.now >= exp]:
            self._counts.pop(key, None)
            self._expire_at.pop(key, None)

    def do_incr(self, key: str) -> int:
        self._sweep()
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    def do_ttl(self, key: str) -> int:
        self._sweep()
        if key not in self._counts:
            return -2
        if key not in self._expire_at:
            return -1
        return max(self._expire_at[key] - self.now, 0)

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    def expire(self, key: str, seconds: int) -> None:
        self._sweep()
        if key in self._counts:
            self._expire_at[key] = self.now + seconds

    def advance(self, seconds: int) -> None:
        self.now += seconds


def _redis_limiter(fake: _FakeRedis) -> RedisRateLimiter:
    """Build a RedisRateLimiter wired to the fake client instead of a live Redis."""
    with patch("app.security.rate_limit.redis_lib.from_url", return_value=fake):
        return RedisRateLimiter("redis://fake:6379/0")


def test_redis_limiter_first_hit_pins_window() -> None:
    """First hit has no TTL (-1), so the limiter pins and reports the full window."""
    limiter = _redis_limiter(_FakeRedis())
    decision = limiter.check("k", limit=3, window_seconds=60)
    assert decision.allowed is True
    assert decision.retry_after == 60


def test_redis_limiter_retry_after_tracks_real_ttl() -> None:
    """retry_after reflects the real remaining TTL, not a hard-coded window."""
    fake = _FakeRedis()
    limiter = _redis_limiter(fake)
    limiter.check("k", limit=3, window_seconds=60)  # pins expiry at now+60
    fake.advance(10)
    decision = limiter.check("k", limit=3, window_seconds=60)
    assert decision.allowed is True
    assert decision.retry_after == 50


def test_redis_limiter_throttles_over_limit() -> None:
    """The (limit+1)-th hit within the window is throttled with a positive retry_after."""
    limiter = _redis_limiter(_FakeRedis())
    for _ in range(3):
        assert limiter.check("k", limit=3, window_seconds=60).allowed is True
    decision = limiter.check("k", limit=3, window_seconds=60)
    assert decision.allowed is False
    assert decision.retry_after > 0


def test_redis_limiter_window_resets_after_expiry() -> None:
    """Once the window elapses the key is evicted and requests are allowed again."""
    fake = _FakeRedis()
    limiter = _redis_limiter(fake)
    for _ in range(3):
        limiter.check("k", limit=3, window_seconds=60)
    assert limiter.check("k", limit=3, window_seconds=60).allowed is False

    fake.advance(60)  # window elapses → counter restarts on the next hit

    reset = limiter.check("k", limit=3, window_seconds=60)
    assert reset.allowed is True
    assert reset.retry_after == 60  # a fresh window is re-pinned


def test_redis_limiter_keys_are_independent() -> None:
    """Distinct keys (e.g. per-IP vs per-account) hold independent counters."""
    fake = _FakeRedis()
    limiter = _redis_limiter(fake)
    for _ in range(3):
        limiter.check("ip", limit=3, window_seconds=60)
    assert limiter.check("ip", limit=3, window_seconds=60).allowed is False
    # A different key is unaffected by the exhausted one.
    assert limiter.check("acct", limit=3, window_seconds=60).allowed is True

"""HTTP/IO client for the local v1 food dogfood smoke (FTY-256, FTY-356).

The side-effectful slice of the food dogfood smoke: the minimal bearer-auth JSON
client that talks to the live local API, the response-parsing helpers that turn
raw DTOs into the sanitized :class:`SmokeItem` view, the token-subject decode the
login flow needs, the poll loop that waits each submitted event to a terminal
estimation state, and the ``acquire_account`` login-first/register-once bootstrap
that runs the account IO flow. :mod:`app.ops.food_dogfood_smoke` owns the pure
assessment layer and the ``run()``/``main()`` orchestration that wires this client
to it (FTY-356 split the two so neither module crowds the code-shape source ceiling).

Everything here either performs IO against the live stack or shapes a live
response for assessment. It is sanitized by construction: the bearer token is
sent only in the ``Authorization`` header and never returned in any string this
module builds, and error/response bodies are read for a status code only, never
surfaced.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from base64 import urlsafe_b64decode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.ops.food_dogfood_fixtures import FixtureSpec

__all__ = [
    "ApiClient",
    "EventUnderTest",
    "SmokeError",
    "SmokeItem",
    "acquire_account",
    "poll_all",
]

# --------------------------------------------------------------------------- #
# Tuning constants.
# --------------------------------------------------------------------------- #

#: The terminal estimation statuses a submitted event can settle into.
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "needs_clarification", "partially_resolved"}
)

#: Per-event poll budget: how long to wait for estimation to finish, and the
#: gap between polls. Live estimation (search + fetch + LLM) can take a while,
#: so the ceiling is generous; the worker normally finishes far sooner.
POLL_TIMEOUT_SECONDS = 90.0
POLL_INTERVAL_SECONDS = 2.0

#: HTTP status codes the client treats as success.
_HTTP_OK = 200
_HTTP_CREATED = 201

#: HTTP 401: the login endpoint's answer for a missing account or bad credentials.
#: The smoke reads it as "not registered yet".
_HTTP_UNAUTHORIZED = 401


class SmokeError(Exception):
    """A fatal, operator-facing smoke error (stack down, auth failed, …).

    Its message is sanitized (no bearer token, credentials, or raw response
    body), so it is safe to print directly.
    """


@dataclass(frozen=True)
class SmokeItem:
    """The sanitized, structured view of one derived item the smoke evaluates."""

    name: str
    source_type: str | None
    source_ref: str | None
    source_label: str | None
    calories: float | None


def _user_id_from_token(token: str) -> str:
    """Extract the subject user id from a bearer token's payload segment (pure).

    A token is ``<payload_b64url>.<signature>`` with payload ``{"sub": <user id>,
    …}`` (see :mod:`app.security.tokens`). ``/api/auth/login`` returns only the
    token, not the user record, so the smoke reads the ``sub`` claim to build the
    ``/api/users/{id}`` path. The signature is not verified — the smoke trusts its
    own local stack and the server re-checks ownership on every request.
    """

    try:
        payload_b64 = token.split(".", 1)[0]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(urlsafe_b64decode(payload_b64 + padding))
        subject = payload["sub"]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise SmokeError("login token payload was unreadable") from None
    if not isinstance(subject, str) or not subject:
        raise SmokeError("login token payload missing a subject")
    return subject


@dataclass
class ApiClient:
    """Minimal bearer-authenticated JSON client over the live local API.

    Uses :mod:`urllib` (no new dependency), fixed URLs, and a short timeout. The
    bearer token is sent only in the ``Authorization`` header, never returned in
    any string this module prints.
    """

    base_url: str
    token: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
    ) -> tuple[int, object | None]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"content-type": "application/json"} if data is not None else {}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(  # noqa: S310 — fixed http loopback URL
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as resp:  # noqa: S310
                return resp.status, _load_json(resp.read())
        except urllib.error.HTTPError as exc:
            # Read the error body for a status only; never surface its contents.
            return exc.code, _load_json(exc.read())
        except (urllib.error.URLError, OSError) as exc:
            raise SmokeError(
                f"cannot reach the local API at {self.base_url} "
                f"({exc.__class__.__name__}) — is the stack up? `docker compose up -d`"
            ) from None

    def register(self, email: str, password: str) -> str:
        """Register a throwaway account; return its bearer token."""

        status_code, payload = self._request(
            "POST", "/api/auth/register", body={"email": email, "password": password}
        )
        if status_code not in (_HTTP_OK, _HTTP_CREATED) or not isinstance(payload, Mapping):
            raise SmokeError(
                f"account registration failed (HTTP {status_code}); "
                "the stack may be unmigrated or unhealthy"
            )
        token = _dig(payload, "token", "access_token")
        user_id = _dig(payload, "user", "id")
        if not isinstance(token, str) or not isinstance(user_id, str):
            raise SmokeError("registration response missing a token or user id")
        self.token = token
        return user_id

    def login(self, email: str, password: str) -> str | None:
        """Log in to the throwaway account; return its user id, or ``None`` if absent.

        ``None`` on HTTP 401 (the login endpoint's answer for both a missing
        account and a bad password) signals the caller to register it once. Any
        other failure (down stack, a 429 from the login limiter) raises.
        """

        status_code, payload = self._request(
            "POST", "/api/auth/login", body={"email": email, "password": password}
        )
        if status_code == _HTTP_UNAUTHORIZED:
            return None
        if status_code != _HTTP_OK or not isinstance(payload, Mapping):
            raise SmokeError(
                f"login to the throwaway account failed (HTTP {status_code}); "
                "the stack may be unhealthy or the login rate limit was hit"
            )
        token = payload.get("access_token")
        if not isinstance(token, str):
            raise SmokeError("login response missing an access token")
        self.token = token
        return _user_id_from_token(token)

    def submit(self, user_id: str, raw_text: str) -> str:
        """Submit one food log; return the created event id."""

        status_code, payload = self._request(
            "POST", f"/api/users/{user_id}/log-events", body={"raw_text": raw_text}
        )
        if status_code not in (_HTTP_OK, _HTTP_CREATED) or not isinstance(payload, Mapping):
            raise SmokeError(f"submitting a log event failed (HTTP {status_code})")
        event_id = payload.get("id")
        if not isinstance(event_id, str):
            raise SmokeError("log-event create response missing an id")
        return event_id

    def poll_status(self, user_id: str, event_id: str) -> str:
        """GET one event's current status (empty string if unreadable)."""

        status_code, payload = self._request("GET", f"/api/users/{user_id}/log-events/{event_id}")
        if status_code != _HTTP_OK or not isinstance(payload, Mapping):
            return ""
        status_value = payload.get("status")
        return status_value if isinstance(status_value, str) else ""

    def read_entries(self, user_id: str) -> Mapping[str, list[SmokeItem]]:
        """Read today's entries; map event id → its sanitized derived items."""

        status_code, payload = self._request("GET", f"/api/users/{user_id}/log-events/by-date")
        if status_code != _HTTP_OK or not isinstance(payload, Sequence):
            return {}
        by_event: dict[str, list[SmokeItem]] = {}
        for entry in payload:
            if not isinstance(entry, Mapping):
                continue
            event = entry.get("event")
            event_id = event.get("id") if isinstance(event, Mapping) else None
            if not isinstance(event_id, str):
                continue
            items = entry.get("items")
            by_event[event_id] = _extract_items(items)
        return by_event

    def read_clarifications(self, user_id: str, event_id: str) -> tuple[str, ...]:
        """Read a needs_clarification/partially_resolved event's question text."""

        status_code, payload = self._request(
            "GET", f"/api/users/{user_id}/log-events/{event_id}/clarification"
        )
        if status_code != _HTTP_OK or not isinstance(payload, Mapping):
            return ()
        questions = payload.get("questions")
        if not isinstance(questions, Sequence):
            return ()
        texts = [
            q["text"]
            for q in questions
            if isinstance(q, Mapping) and isinstance(q.get("text"), str)
        ]
        return tuple(texts)


def _load_json(raw: bytes) -> object | None:
    try:
        parsed: object = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed


def _dig(payload: Mapping[str, object], *keys: str) -> object | None:
    """Walk nested mappings by ``keys``; return None if any hop is missing."""

    current: object | None = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _extract_items(items: object) -> list[SmokeItem]:
    """Map raw ``items`` DTOs to the sanitized :class:`SmokeItem` view."""

    result: list[SmokeItem] = []
    if not isinstance(items, Sequence):
        return result
    for item in items:
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        source_type = _dig(source, "source_type") if isinstance(source, Mapping) else None
        source_ref = _dig(source, "ref") if isinstance(source, Mapping) else None
        source_label = _dig(source, "label") if isinstance(source, Mapping) else None
        calories = item.get("calories")
        result.append(
            SmokeItem(
                name=str(item.get("name", "?")),
                source_type=source_type if isinstance(source_type, str) else None,
                source_ref=source_ref if isinstance(source_ref, str) else None,
                source_label=source_label if isinstance(source_label, str) else None,
                calories=float(calories) if isinstance(calories, (int, float)) else None,
            )
        )
    return result


@dataclass
class EventUnderTest:
    """One submitted fixture event being polled to a terminal status."""

    spec: FixtureSpec
    event_id: str
    status: str = "pending"


def poll_all(
    client: ApiClient,
    user_id: str,
    pending: list[EventUnderTest],
    *,
    sleep: object = time.sleep,
    monotonic: object = time.monotonic,
) -> None:
    """Poll every submitted event until terminal or the shared timeout.

    ``sleep`` / ``monotonic`` are injectable so the loop stays testable, though
    the live orchestration is not part of the unit suite.
    """

    deadline = monotonic() + POLL_TIMEOUT_SECONDS  # type: ignore[operator]
    remaining = {e.event_id: e for e in pending}
    while remaining and monotonic() < deadline:  # type: ignore[operator]
        for event in list(remaining.values()):
            event.status = client.poll_status(user_id, event.event_id)
            if event.status in _TERMINAL_STATUSES:
                del remaining[event.event_id]
        if remaining:
            sleep(POLL_INTERVAL_SECONDS)  # type: ignore[operator]
    for event in remaining.values():
        event.status = event.status or "timeout"


def acquire_account(client: ApiClient, email: str, password: str) -> str:
    """Return the throwaway account's user id, bootstrapping it once if absent.

    Login-first makes the smoke safe to run repeatedly: only the first run on a
    stack registers (one register-limiter slot ever), every later run uses the
    more generous login limiter, so the smoke never trips the default
    5-registrations-per-hour ceiling before a food fixture is exercised.

    ``email``/``password`` are the caller's throwaway credentials (see
    :func:`app.ops.food_dogfood_smoke.throwaway_credentials`); taking them as
    arguments keeps the credential constants on the smoke side of the split.
    """

    user_id = client.login(email, password)
    if user_id is not None:
        return user_id
    # First run on this stack (or the account was reset): register it once.
    return client.register(email, password)

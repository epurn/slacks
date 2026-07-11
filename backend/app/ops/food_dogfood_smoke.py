"""Local v1 food dogfood smoke (FTY-256).

Operator command that proves v1 **food logging is usable on the live local
backend** before a human opens the simulator. It signs in to a dedicated
throwaway account, submits a small set of representative food logs to the running
local API (derived from ``.env`` ``API_PORT``, exactly as
:mod:`app.ops.sim_readiness`), waits for each event to reach a terminal
estimation state, and prints a sanitized pass/fail summary with per-item
source/provenance and calories. It catches the v1 dogfood regressions the
hermetic suites cannot see — a *live* clarify on a counted entry, a branded item
matched to a generic FDC row (the 2026-07-10 ``Compliments`` → ``DENNY'S``
failure), a banana costed as **powder**, or a branded snack that fails to
complete with honest provenance.

This is **live-local API smoke**, not the hermetic E2E fixture mode
(``mobile/verify-e2e.sh``): every request hits FastAPI, Postgres, the worker, and
the configured evidence/LLM providers, so it needs a healthy stack with a **real
LLM provider** (``claude_code`` / ``codex`` / ``openai_compatible`` — the default
``fake`` cannot parse natural-language food). It is **not** wired into ``make
verify`` and must never become a CI gate depending on live external providers
(story Non-Goals); only its pure parsing/redaction/assessment logic is unit-tested.

Design constraints (mirroring :mod:`app.ops.sim_readiness`):

- **Reused throwaway account, repeatable.** The smoke reuses one *deterministic*
  throwaway account (fixed fixture email + non-secret password), logging in each
  run and registering only when it does not exist yet. Login-first keeps repeat
  runs off the register rate limiter (default 5/IP/hour) — registering afresh per
  run would trip that ceiling and fail a *healthy* stack before any food fixture
  ran. The account is dedicated to the smoke, never a real user, so reusing it
  pollutes no real user data.
- **No secrets.** It reads ``.env`` only for the non-secret ``API_PORT`` and never
  prints ``.env`` contents, the bearer token, provider keys, DB passwords, or raw
  provider output — output is built from structured fields only (status, fixture
  text, source type/ref, calories, sanitized clarification text).

Run it from the repo root once the stack is up and a provider is logged in::

    make food-smoke  # or: cd backend && uv run python -m app.ops.food_dogfood_smoke
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.error
import urllib.request
from base64 import urlsafe_b64decode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.ops.food_dogfood_fixtures import FIXTURES, FixtureSpec, ItemBand, load_fixtures
from app.ops.sim_readiness import (
    parse_api_port,
    parse_env,
    read_env_file,
    simulator_url,
)

# ``FixtureSpec``/``ItemBand``/``load_fixtures``/``FIXTURES`` are the fixture
# data-model + JSON loader, kept in a sibling module next to the JSON data
# (``food_dogfood_fixtures.py`` / ``.json``) so this module stays focused on
# orchestration + assessment. Re-exported here so the smoke's public surface and
# its unit tests keep a single import point.
__all__ = [
    "FIXTURES",
    "FixtureSpec",
    "ItemBand",
    "assess_fixture",
    "load_fixtures",
    "run",
]

# --------------------------------------------------------------------------- #
# Tuning constants.
# --------------------------------------------------------------------------- #

#: The terminal estimation statuses a submitted event can settle into.
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "needs_clarification", "partially_resolved"}
)

#: Statuses that mean the food step could not cost the entry — a live regression
#: for any fixture that supplied a count or measured amount.
_NON_COMPLETED_TERMINAL: frozenset[str] = frozenset(
    {"failed", "needs_clarification", "partially_resolved"}
)

#: Per-event poll budget: how long to wait for estimation to finish, and the
#: gap between polls. Live estimation (search + fetch + LLM) can take a while,
#: so the ceiling is generous; the worker normally finishes far sooner.
POLL_TIMEOUT_SECONDS = 90.0
POLL_INTERVAL_SECONDS = 2.0

#: Per-item sanity ceiling. A single logged food item costing more than this is
#: implausible for these everyday fixtures and signals a bad match/scale.
PER_ITEM_ABSURD_KCAL = 2000.0

#: HTTP status codes the client treats as success.
_HTTP_OK = 200
_HTTP_CREATED = 201

#: HTTP 401: the login endpoint's answer for a missing account or bad credentials.
#: The smoke reads it as "not registered yet".
_HTTP_UNAUTHORIZED = 401

#: The deterministic throwaway account, reused across runs (login-first) so the
#: smoke registers at most once per stack. A dedicated fixture identity, never a
#: real user. The password satisfies the register bounds (8–128 chars).
_FIXTURE_EMAIL = "dogfood-smoke@fatty.local"
_FIXTURE_PASSWORD = "dogfood-smoke-pw"  # noqa: S105 — non-secret local fixture


# --------------------------------------------------------------------------- #
# Fixtures + expected outcomes (pure data).
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Pure helpers: URL, credentials, assessment.
# --------------------------------------------------------------------------- #


def api_base_url(api_port: int) -> str:
    """The live-local API base URL a host process reaches the stack at.

    Reuses the simulator connect URL — the published API sits on host loopback
    at ``http://localhost:<API_PORT>`` — so the smoke and the sim-readiness
    report agree on the one v1 target.
    """

    return simulator_url(api_port)


def throwaway_credentials() -> tuple[str, str]:
    """Return the deterministic ``(email, password)`` for the throwaway account.

    Fixed, non-secret fixture values reused across runs so the smoke logs in to
    one dedicated account (never a real user) instead of registering afresh each
    run — a fresh registration per run would trip the register rate limiter
    (default 5/IP/hour) and fail a healthy stack before any food fixture ran.
    """

    return (_FIXTURE_EMAIL, _FIXTURE_PASSWORD)


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


@dataclass(frozen=True)
class SmokeItem:
    """The sanitized, structured view of one derived item the smoke evaluates."""

    name: str
    source_type: str | None
    source_ref: str | None
    source_label: str | None
    calories: float | None


@dataclass(frozen=True)
class FixtureOutcome:
    """The live result of one fixture: terminal status, items, clarification."""

    status: str
    items: tuple[SmokeItem, ...]
    #: Sanitized clarification question text, when the event asked one.
    clarification_texts: tuple[str, ...] = ()


@dataclass(frozen=True)
class FixtureAssessment:
    """Pass/fail verdict for one fixture plus operator-facing detail lines."""

    spec: FixtureSpec
    outcome: FixtureOutcome
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


def _finite_positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _status_failures(status: str) -> list[str]:
    """Terminal-status check: a supplied count/amount must complete, never clarify."""

    if status == "completed":
        return []
    if status in _NON_COMPLETED_TERMINAL:
        return [
            f"expected 'completed' but got '{status}' "
            "(a supplied count/amount must resolve, not clarify/fail)"
        ]
    return [f"did not reach 'completed' (status '{status}')"]


def _count_failures(spec: FixtureSpec, items: Sequence[SmokeItem]) -> list[str]:
    """Derived-item-count check against the fixture's expectation."""

    if spec.expected_item_count is not None and len(items) != spec.expected_item_count:
        return [f"expected {spec.expected_item_count} derived item(s), got {len(items)}"]
    if spec.expected_item_count is None and not items:
        return ["no derived items produced"]
    return []


def _item_haystack(item: SmokeItem) -> str:
    """The lowercase name/label/ref text substring checks scan."""

    return " ".join(
        part.lower() for part in (item.name, item.source_label, item.source_ref) if part
    )


def _item_failures(spec: FixtureSpec, item: SmokeItem) -> list[str]:
    """Per-item provenance, calories, and forbidden-match checks."""

    failures: list[str] = []
    if not item.source_type:
        failures.append(f"item '{item.name}' has no source provenance")
    elif item.source_type in {st.value for st in spec.forbid_source_types}:
        failures.append(
            f"item '{item.name}' resolved via forbidden source '{item.source_type}' "
            "(a branded item must not complete from a generic FDC row)"
        )

    if not _finite_positive(item.calories):
        failures.append(
            f"item '{item.name}' has no positive calories "
            f"(got {item.calories!r}) — a silent zero is not an acknowledgement"
        )
    elif (item.calories or 0.0) > PER_ITEM_ABSURD_KCAL:
        failures.append(
            f"item '{item.name}' calories {item.calories:.0f} exceed the "
            f"plausibility ceiling {PER_ITEM_ABSURD_KCAL:.0f}"
        )

    haystack = _item_haystack(item)
    failures.extend(
        f"item '{item.name}' matched forbidden form '{sub}'"
        for sub in spec.forbid_substrings
        if sub in haystack
    )
    return failures


def _expected_item_failures(spec: FixtureSpec, items: Sequence[SmokeItem]) -> list[str]:
    """Per-item plausibility bands for multi-item fixtures.

    Each band must match at least one derived item, and every matched item's
    calories must fall inside its band — so a bad split cannot hide behind a
    passing **total** band.
    """

    failures: list[str] = []
    for band in spec.expected_items:
        matched = [item for item in items if band.match in _item_haystack(item)]
        if not matched:
            failures.append(
                f"no derived item matched expected item '{band.match}' "
                "(the multi-item split did not produce it)"
            )
            continue
        for item in matched:
            # Missing/zero calories are already flagged by the per-item check.
            if not _finite_positive(item.calories):
                continue
            if not (band.kcal_low <= (item.calories or 0.0) <= band.kcal_high):
                failures.append(
                    f"item '{item.name}' calories {item.calories:.0f} outside the "
                    f"per-item plausible band [{band.kcal_low:.0f}, "
                    f"{band.kcal_high:.0f}] for '{band.match}'"
                )
    return failures


def assess_fixture(spec: FixtureSpec, outcome: FixtureOutcome) -> FixtureAssessment:
    """Evaluate a fixture's live outcome against its expected behavior (pure).

    Returns every failed assertion (not just the first) so the operator sees all
    the ways a run regressed; an empty list means expected v1 behavior.
    """

    failures: list[str] = []
    failures += _status_failures(outcome.status)
    failures += _count_failures(spec, outcome.items)
    for item in outcome.items:
        failures += _item_failures(spec, item)
    failures += _expected_item_failures(spec, outcome.items)

    # Total calorie band — the primary detector for a wrong-form match (e.g.
    # banana powder). Only checked once real calories were produced.
    costed = [item.calories for item in outcome.items if _finite_positive(item.calories)]
    if costed:
        total = sum(costed)  # type: ignore[arg-type]
        if not (spec.total_kcal_low <= total <= spec.total_kcal_high):
            failures.append(
                f"total calories {total:.0f} outside the plausible band "
                f"[{spec.total_kcal_low:.0f}, {spec.total_kcal_high:.0f}]"
            )

    return FixtureAssessment(spec=spec, outcome=outcome, failures=tuple(failures))


def _format_item(item: SmokeItem) -> str:
    """One sanitized per-item line: name, source type/ref, calories."""

    source = item.source_type or "no-source"
    ref = f" {item.source_ref}" if item.source_ref else ""
    cals = f"{item.calories:.0f} kcal" if _finite_positive(item.calories) else "no kcal"
    return f"{item.name} — {source}{ref} — {cals}"


def format_assessment(assessment: FixtureAssessment) -> list[str]:
    """Render a fixture's verdict as sanitized operator-facing lines.

    Prints only structured, non-secret fields (fixture text, status, per-item
    source/ref/calories, sanitized clarification text, failed assertions) — never
    the bearer token, provider keys, or raw provider output.
    """

    mark = "PASS" if assessment.passed else "FAIL"
    lines = [
        f"[{mark}] {assessment.spec.key}: {assessment.spec.raw_text!r}",
        f"       status: {assessment.outcome.status}",
    ]
    lines += [f"       - {_format_item(item)}" for item in assessment.outcome.items]
    lines += [f"       ? clarification: {text}" for text in assessment.outcome.clarification_texts]
    lines += [f"       ! {failure}" for failure in assessment.failures]
    return lines


# --------------------------------------------------------------------------- #
# HTTP orchestration (side-effectful).
# --------------------------------------------------------------------------- #


class SmokeError(Exception):
    """A fatal, operator-facing smoke error (stack down, auth failed, …).

    Its message is sanitized (no bearer token, credentials, or raw response
    body), so it is safe to print directly.
    """


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
class _EventUnderTest:
    spec: FixtureSpec
    event_id: str
    status: str = "pending"


def _poll_all(
    client: ApiClient,
    user_id: str,
    pending: list[_EventUnderTest],
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


# --------------------------------------------------------------------------- #
# Report assembly.
# --------------------------------------------------------------------------- #


def acquire_account(client: ApiClient) -> str:
    """Return the throwaway account's user id, bootstrapping it once if absent.

    Login-first makes the smoke safe to run repeatedly: only the first run on a
    stack registers (one register-limiter slot ever), every later run uses the
    more generous login limiter, so the smoke never trips the default
    5-registrations-per-hour ceiling before a food fixture is exercised.
    """

    email, password = throwaway_credentials()
    user_id = client.login(email, password)
    if user_id is not None:
        return user_id
    # First run on this stack (or the account was reset): register it once.
    return client.register(email, password)


def _emit(line: str = "") -> None:
    print(line)


def _assess_all(
    client: ApiClient, user_id: str, submitted: Sequence[_EventUnderTest]
) -> list[FixtureAssessment]:
    """Read each terminal event's items/clarification and assess every fixture."""

    items_by_event = client.read_entries(user_id)
    assessments: list[FixtureAssessment] = []
    for event in submitted:
        clarifications: tuple[str, ...] = ()
        if event.status in {"needs_clarification", "partially_resolved"}:
            clarifications = client.read_clarifications(user_id, event.event_id)
        outcome = FixtureOutcome(
            status=event.status,
            items=tuple(items_by_event.get(event.event_id, ())),
            clarification_texts=clarifications,
        )
        assessments.append(assess_fixture(event.spec, outcome))
    return assessments


def run() -> int:
    """Run the live food dogfood smoke; return a shell exit code."""

    _emit("Fatty local v1 food dogfood smoke (FTY-256)")
    _emit("=" * 46)
    _emit("Live-local API smoke — NOT the hermetic E2E fixture mode.")

    env_text = read_env_file()
    if env_text is None:
        _emit("FAIL: no .env at repo root. Run `cp .env.example .env` first.")
        return 1
    env = parse_env(env_text)
    try:
        api_port = parse_api_port(env)
    except ValueError as exc:
        _emit(f"FAIL: {exc}")
        return 1
    base_url = api_base_url(api_port)
    _emit(f"Target: {base_url}")

    client = ApiClient(base_url=base_url)
    email, _ = throwaway_credentials()
    _emit(f"Throwaway account: {email} (reused; registered once per stack)")

    try:
        user_id = acquire_account(client)
        submitted = [
            _EventUnderTest(spec=spec, event_id=client.submit(user_id, spec.raw_text))
            for spec in FIXTURES
        ]
    except SmokeError as exc:
        _emit(f"FAIL: {exc}")
        return 1

    _emit(f"Submitted {len(submitted)} fixtures; polling for terminal status…")
    try:
        _poll_all(client, user_id, submitted)
        assessments = _assess_all(client, user_id, submitted)
    except SmokeError as exc:
        _emit(f"FAIL: {exc}")
        return 1

    _emit("")
    for assessment in assessments:
        for line in format_assessment(assessment):
            _emit(line)
        _emit("")

    passed = sum(1 for a in assessments if a.passed)
    total = len(assessments)
    if passed == total:
        _emit(f"PASS: all {total} fixtures reached the expected v1 behavior.")
        return 0
    _emit(f"FAIL: {total - passed} of {total} fixtures regressed (see ! lines above).")
    _emit("This is the live local backend, so a failure means a real v1 dogfood")
    _emit("regression (or a stack/provider not configured for live estimation).")
    return 1


def main() -> None:
    """Console entry point (``python -m app.ops.food_dogfood_smoke``)."""

    sys.exit(run())


if __name__ == "__main__":
    main()

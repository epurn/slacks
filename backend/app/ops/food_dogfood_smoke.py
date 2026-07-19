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

This module owns the **pure assessment layer** (fixture-outcome verdicts and the
sanitized report formatting) and the ``run()``/``main()`` orchestration that
wires it to the side-effectful HTTP/IO client. That client — :class:`ApiClient`,
the response-parsing helpers, the poll loop, and the ``acquire_account`` account
bootstrap — lives in :mod:`app.ops.food_dogfood_api` (FTY-356 split the two so
neither module crowds
the code-shape source ceiling); the fixture data-model + JSON loader live in
:mod:`app.ops.food_dogfood_fixtures`.

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

import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from app.ops.food_dogfood_api import (
    ApiClient,
    EventUnderTest,
    SmokeError,
    SmokeItem,
    acquire_account,
    poll_all,
)
from app.ops.food_dogfood_fixtures import FIXTURES, FixtureSpec, ItemBand, load_fixtures
from app.ops.sim_readiness import (
    parse_api_port,
    parse_env,
    read_env_file,
    simulator_url,
)

# ``FixtureSpec``/``ItemBand``/``load_fixtures``/``FIXTURES`` are the fixture
# data-model + JSON loader (:mod:`app.ops.food_dogfood_fixtures`); ``ApiClient``/
# ``SmokeError``/``SmokeItem`` are the HTTP/IO client slice
# (:mod:`app.ops.food_dogfood_api`). Both are re-exported here so the smoke's
# public surface and its unit tests keep a single import point for the data
# model and the sanitized item view that assessment consumes.
__all__ = [
    "FIXTURES",
    "ApiClient",
    "FixtureSpec",
    "ItemBand",
    "SmokeError",
    "SmokeItem",
    "assess_fixture",
    "load_fixtures",
    "run",
]

# --------------------------------------------------------------------------- #
# Tuning constants.
# --------------------------------------------------------------------------- #

#: Statuses that mean the food step could not cost the entry — a live regression
#: for any fixture that supplied a count or measured amount.
_NON_COMPLETED_TERMINAL: frozenset[str] = frozenset(
    {"failed", "needs_clarification", "partially_resolved"}
)

#: Terminal states that satisfy a ``never_fail`` fixture (FTY-373): a rough
#: degraded estimate lands ``completed``; a mixed log lands ``partially_resolved``.
#: Both are honest "estimated" outcomes. Terminal ``failed`` (infra breach
#: surfaced as a failed entry) and ``needs_clarification`` (a reflexive question
#: instead of an estimate) are *not* a never-fail pass.
_NEVER_FAIL_TERMINAL_PASS: frozenset[str] = frozenset({"completed", "partially_resolved"})

#: Per-item sanity ceiling. A single logged food item costing more than this is
#: implausible for these everyday fixtures and signals a bad match/scale.
PER_ITEM_ABSURD_KCAL = 2000.0

#: The deterministic throwaway account, reused across runs (login-first) so the
#: smoke registers at most once per stack. A dedicated fixture identity, never a
#: real user. The password satisfies the register bounds (8–128 chars).
_FIXTURE_EMAIL = "dogfood-smoke@slacks.local"
_FIXTURE_PASSWORD = "dogfood-smoke-pw"  # noqa: S105 — non-secret local fixture


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


def _status_failures(status: str, *, never_fail: bool) -> list[str]:
    """Terminal-status check.

    Default (strict) fixtures: a supplied count/amount must ``complete``, never
    clarify or fail. ``never_fail`` fixtures (FTY-373) only have to reach a
    terminal non-``failed`` estimate — a rough degraded ``completed`` or a
    ``partially_resolved`` passes; terminal ``failed`` (an infra breach surfaced
    as a failed entry) and a reflexive ``needs_clarification`` do not.
    """

    if status == "completed":
        return []
    if never_fail:
        if status in _NEVER_FAIL_TERMINAL_PASS:
            return []
        if status == "failed":
            return [
                "ended in terminal 'failed' — the never-fail invariant forbids a "
                "deadline/budget/transient breach from surfacing as a failed entry"
            ]
        return [
            f"expected a terminal estimate but got '{status}' "
            "(an informal/consumable phrase must be estimated, not clarified/failed)"
        ]
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
    failures += _status_failures(outcome.status, never_fail=spec.never_fail)
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
# Report assembly + orchestration.
# --------------------------------------------------------------------------- #


def _emit(line: str = "") -> None:
    print(line)


def _assess_all(
    client: ApiClient, user_id: str, submitted: Sequence[EventUnderTest]
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

    _emit("Slacks local v1 food dogfood smoke (FTY-256)")
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
    email, password = throwaway_credentials()
    _emit(f"Throwaway account: {email} (reused; registered once per stack)")

    try:
        user_id = acquire_account(client, email, password)
        submitted = [
            EventUnderTest(spec=spec, event_id=client.submit(user_id, spec.raw_text))
            for spec in FIXTURES
        ]
    except SmokeError as exc:
        _emit(f"FAIL: {exc}")
        return 1

    _emit(f"Submitted {len(submitted)} fixtures; polling for terminal status…")
    try:
        poll_all(client, user_id, submitted)
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

"""Fixture data-model + loader for the local food dogfood smoke (FTY-256).

The representative food logs the smoke submits, and the outcome each must
deliver, live as **data** in ``food_dogfood_fixtures.json`` (not a Python
literal) so the smoke hardcodes no brand phrase — the exact 2026-07-10 snack
phrase and its brand tokens stay out of ``backend/app`` executable source,
keeping the estimator's no-special-case scan
(``test_exact_snack_phrase_resolution``) valid. This module owns the typed
loader for that JSON; :mod:`app.ops.food_dogfood_smoke` owns the orchestration
and assessment that consume it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.enums import SourceType


@dataclass(frozen=True)
class ItemBand:
    """Per-item plausibility band for one expected derived item.

    ``match`` is a lowercase substring of the item's name/label/ref (the haystack
    ``forbid_substrings`` scans); the matched item's calories must fall inside the
    inclusive ``[kcal_low, kcal_high]`` band. This keeps a multi-item fixture
    honest — a total-only band would let a bad split (crackers=1 + hummus=399) pass.
    """

    match: str
    kcal_low: float
    kcal_high: float


@dataclass(frozen=True)
class FixtureSpec:
    """One representative food log plus the outcome the live stack must deliver.

    The assertions encode the FTY-252/253/254 dogfood regression class: a supplied
    count/amount must resolve (never a generic quantity clarification), a branded
    item must not complete via a generic FDC row, a banana must not cost as powder
    (caught by the calorie band), and every item must carry honest provenance.
    """

    key: str
    raw_text: str
    #: Exact number of derived items expected, or ``None`` for "at least one".
    expected_item_count: int | None
    #: Inclusive plausible band for the entry's **total** calories.
    total_kcal_low: float
    total_kcal_high: float
    #: ``source_type`` values that would be a wrong resolution for this fixture
    #: (e.g. a generic ``trusted_nutrition_database`` row for a branded item).
    forbid_source_types: tuple[SourceType, ...] = ()
    #: Substrings that must not appear in an item's name/label/ref (defensive;
    #: the calorie band is the primary detector for a wrong-form match).
    forbid_substrings: tuple[str, ...] = ()
    #: Per-item plausibility bands for multi-item fixtures. Each band must match
    #: a derived item, and every matched item must cost inside its band, so the
    #: total band cannot be satisfied by an implausible split.
    expected_items: tuple[ItemBand, ...] = ()


_FIXTURES_PATH = Path(__file__).with_name("food_dogfood_fixtures.json")


def load_fixtures(path: Path | None = None) -> tuple[FixtureSpec, ...]:
    """Load the representative food-log fixtures from the JSON data file (pure).

    ``path`` is injectable for tests. Raises if the data is missing or malformed
    — the smoke has no fixtures to run without it, so failing loudly beats a
    silently empty run.
    """

    source = path or _FIXTURES_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    raw_fixtures = payload["fixtures"]
    return tuple(_fixture_from_dict(entry) for entry in raw_fixtures)


def _str_list(value: object) -> tuple[str, ...]:
    """Coerce a JSON list (or absent value) into a tuple of strings."""

    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _item_bands(value: object) -> tuple[ItemBand, ...]:
    """Coerce a JSON ``expected_items`` list (or absent value) into bands."""

    if not isinstance(value, list):
        return ()
    return tuple(
        ItemBand(
            match=str(entry["match"]).lower(),
            kcal_low=float(entry["kcal_low"]),
            kcal_high=float(entry["kcal_high"]),
        )
        for entry in value
        if isinstance(entry, Mapping)
    )


def _fixture_from_dict(entry: Mapping[str, object]) -> FixtureSpec:
    """Build one :class:`FixtureSpec` from its JSON object."""

    count = entry["expected_item_count"]
    return FixtureSpec(
        key=str(entry["key"]),
        raw_text=str(entry["raw_text"]),
        expected_item_count=int(count) if isinstance(count, (int, float)) else None,
        total_kcal_low=float(entry["total_kcal_low"]),  # type: ignore[arg-type]
        total_kcal_high=float(entry["total_kcal_high"]),  # type: ignore[arg-type]
        forbid_source_types=tuple(
            SourceType(value) for value in _str_list(entry.get("forbid_source_types"))
        ),
        forbid_substrings=_str_list(entry.get("forbid_substrings")),
        expected_items=_item_bands(entry.get("expected_items")),
    )


#: The representative dogfood set (story Scope), ordered simplest → the
#: 2026-07-10 branded-snack failure the smoke exists to catch.
FIXTURES: tuple[FixtureSpec, ...] = load_fixtures()

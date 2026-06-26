"""Unit tests for the curated, versioned MET table (FTY-043).

Pin the table's lookup contract: canonical keys and aliases resolve
case-/whitespace-insensitively, unmatched activities return ``None`` (so the
calculator fails closed instead of guessing), every curated MET value is above rest
(so the net ``MET - 1`` burn is non-negative), and the table is content-addressed by
a non-empty version/source recorded as run evidence.
"""

from __future__ import annotations

import pytest

from app.estimator.exercise import RESTING_MET
from app.estimator.met_table import (
    MET_TABLE,
    MET_TABLE_SOURCE,
    MET_TABLE_VERSION,
    lookup_met,
)


def test_canonical_key_resolves_to_itself() -> None:
    entry = lookup_met("running")
    assert entry is not None
    assert entry.key == "running"
    assert entry.met == 7.0


@pytest.mark.parametrize(
    ("phrase", "expected_key"),
    [
        ("jog", "running"),
        ("jogging", "running"),
        ("going for a run", "running"),
        ("brisk walk", "walking"),
        ("bike", "cycling"),
        ("lifting weights", "strength_training"),
        ("spin class", "stationary_cycling"),
        ("jump rope", "jump_rope"),
    ],
)
def test_aliases_resolve_to_canonical_entry(phrase: str, expected_key: str) -> None:
    entry = lookup_met(phrase)
    assert entry is not None
    assert entry.key == expected_key


@pytest.mark.parametrize("phrase", ["RUNNING", "  Run  ", "run.", "Jogging!"])
def test_lookup_is_case_and_whitespace_and_punctuation_insensitive(phrase: str) -> None:
    entry = lookup_met(phrase)
    assert entry is not None and entry.key == "running"


@pytest.mark.parametrize("phrase", ["teleporting", "underwater basket weaving", "", "   "])
def test_unmatched_activity_returns_none(phrase: str) -> None:
    # No fuzzy matching: an unrecognized activity must fail closed, not guess.
    assert lookup_met(phrase) is None


def test_every_curated_met_is_above_rest() -> None:
    # 1 MET is rest; a curated value at or below rest would yield a non-positive net
    # burn, which is never a valid active-calorie credit.
    assert all(entry.met > RESTING_MET for entry in MET_TABLE.values())


def test_version_and_source_are_recorded() -> None:
    assert MET_TABLE_VERSION == "met/v1"
    assert MET_TABLE_SOURCE
    assert "Compendium" in MET_TABLE_SOURCE

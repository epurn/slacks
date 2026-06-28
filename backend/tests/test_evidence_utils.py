"""Tests for the shared estimator evidence helpers (FTY-082).

Pins the exact _content_hash fingerprint for a fixed (source_ref, facts) input so
any future change to the hash formula or its inputs is caught immediately.
Also verifies _record_source_ref append-if-absent behaviour.
"""

from __future__ import annotations

import uuid

from app.estimator.evidence_utils import _content_hash, _record_source_ref
from app.estimator.food_serving import NutritionFacts
from app.estimator.pipeline import EstimationContext


def _make_context() -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text="test")


# ---------------------------------------------------------------------------
# _content_hash — determinism pin
# ---------------------------------------------------------------------------


def test_content_hash_deterministic_pin() -> None:
    """The hash for a fixed (source_ref, facts) must never change (stored fingerprints).

    Pin: sha256("usda_fdc:168880|130.0|2.69|28.2|0.28")
    Any change to the formula silently invalidates stored evidence fingerprints.
    """

    facts = NutritionFacts(calories=130.0, protein_g=2.69, carbs_g=28.2, fat_g=0.28)
    result = _content_hash("usda_fdc:168880", facts)
    assert result == "104d02acb28b6c13fe1e40b7897d26e8d78eb6069df2a76b4482c63ab4d7dae8"


def test_content_hash_same_inputs_same_output() -> None:
    facts = NutritionFacts(calories=100.0, protein_g=10.0, carbs_g=20.0, fat_g=5.0)
    assert _content_hash("src:1", facts) == _content_hash("src:1", facts)


def test_content_hash_different_source_ref() -> None:
    facts = NutritionFacts(calories=100.0, protein_g=10.0, carbs_g=20.0, fat_g=5.0)
    assert _content_hash("src:1", facts) != _content_hash("src:2", facts)


def test_content_hash_different_facts() -> None:
    facts_a = NutritionFacts(calories=100.0, protein_g=10.0, carbs_g=20.0, fat_g=5.0)
    facts_b = NutritionFacts(calories=200.0, protein_g=10.0, carbs_g=20.0, fat_g=5.0)
    assert _content_hash("src:1", facts_a) != _content_hash("src:1", facts_b)


def test_content_hash_returns_64_char_hex() -> None:
    facts = NutritionFacts(calories=100.0, protein_g=10.0, carbs_g=20.0, fat_g=5.0)
    result = _content_hash("src:1", facts)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------------
# _record_source_ref — append-if-absent
# ---------------------------------------------------------------------------


def test_record_source_ref_appends_new_source() -> None:
    ctx = _make_context()
    _record_source_ref(ctx, "usda_fdc")
    assert ctx.source_refs == ["usda_fdc"]


def test_record_source_ref_no_duplicate() -> None:
    ctx = _make_context()
    _record_source_ref(ctx, "usda_fdc")
    _record_source_ref(ctx, "usda_fdc")
    assert ctx.source_refs == ["usda_fdc"]


def test_record_source_ref_multiple_sources_ordered() -> None:
    ctx = _make_context()
    _record_source_ref(ctx, "open_food_facts")
    _record_source_ref(ctx, "usda_fdc")
    assert ctx.source_refs == ["open_food_facts", "usda_fdc"]


def test_record_source_ref_second_source_not_duplicated() -> None:
    ctx = _make_context()
    _record_source_ref(ctx, "open_food_facts")
    _record_source_ref(ctx, "usda_fdc")
    _record_source_ref(ctx, "open_food_facts")
    assert ctx.source_refs == ["open_food_facts", "usda_fdc"]

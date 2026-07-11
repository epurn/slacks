"""Unit tests for the local food dogfood smoke (FTY-256).

Cover the pure logic the operator command relies on: the live-local API URL,
throwaway-credential generation, the fixture-outcome assessment (the FTY-252/
253/254 dogfood regression assertions), the sanitized item/DTO extraction, and
the redacted output formatting. The HTTP orchestration and the live poll loop
are intentionally not exercised here — they need a running stack with a real LLM
provider — but every value the report *prints* and every pass/fail decision it
makes flows through a function verified below.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.enums import SourceType
from app.ops import food_dogfood_smoke as smoke

# --------------------------------------------------------------------------- #
# URL + credentials
# --------------------------------------------------------------------------- #


def test_api_base_url_uses_configured_port() -> None:
    assert smoke.api_base_url(18000) == "http://localhost:18000"


def test_throwaway_credentials_are_unique_per_token_and_valid() -> None:
    email_a, password_a = smoke.throwaway_credentials("aaaa")
    email_b, password_b = smoke.throwaway_credentials("bbbb")
    # Unique email per run → repeatable without colliding with a prior account.
    assert email_a != email_b
    assert email_a == "dogfood-smoke+aaaa@fatty.local"
    # Fixed non-secret password that satisfies the register bounds (8–128).
    assert password_a == password_b
    assert 8 <= len(password_a) <= 128


# --------------------------------------------------------------------------- #
# Assessment — happy path
# --------------------------------------------------------------------------- #


def _spec(**overrides: object) -> smoke.FixtureSpec:
    base = {
        "key": "k",
        "raw_text": "text",
        "expected_item_count": 1,
        "total_kcal_low": 50.0,
        "total_kcal_high": 200.0,
    }
    base.update(overrides)
    return smoke.FixtureSpec(**base)  # type: ignore[arg-type]


def _item(**overrides: object) -> smoke.SmokeItem:
    base = {
        "name": "banana",
        "source_type": SourceType.TRUSTED_NUTRITION_DATABASE.value,
        "source_ref": "usda_fdc:123",
        "source_label": "USDA",
        "calories": 105.0,
    }
    base.update(overrides)
    return smoke.SmokeItem(**base)  # type: ignore[arg-type]


def test_completed_fixture_with_plausible_item_passes() -> None:
    outcome = smoke.FixtureOutcome(status="completed", items=(_item(),))
    assessment = smoke.assess_fixture(_spec(), outcome)
    assert assessment.passed
    assert assessment.failures == ()


def test_two_item_snack_passes_when_both_costed() -> None:
    spec = _spec(expected_item_count=2, total_kcal_low=40.0, total_kcal_high=400.0)
    outcome = smoke.FixtureOutcome(
        status="completed",
        items=(
            _item(name="crackers", source_type=SourceType.MODEL_PRIOR.value, calories=80.0),
            _item(name="hummus", source_type=SourceType.REFERENCE_SOURCE.value, calories=45.0),
        ),
    )
    assert smoke.assess_fixture(spec, outcome).passed


# --------------------------------------------------------------------------- #
# Assessment — regression detection
# --------------------------------------------------------------------------- #


def test_live_clarification_on_counted_entry_fails() -> None:
    outcome = smoke.FixtureOutcome(
        status="needs_clarification",
        items=(),
        clarification_texts=("How much banana did you have?",),
    )
    assessment = smoke.assess_fixture(_spec(), outcome)
    assert not assessment.passed
    assert any("needs_clarification" in f for f in assessment.failures)


def test_branded_item_matched_to_generic_fdc_row_fails() -> None:
    spec = _spec(
        key="compliments",
        expected_item_count=1,
        total_kcal_low=80.0,
        total_kcal_high=700.0,
        forbid_source_types=(SourceType.TRUSTED_NUTRITION_DATABASE,),
    )
    outcome = smoke.FixtureOutcome(
        status="completed",
        items=(
            _item(
                name="chicken strips",
                source_type=SourceType.TRUSTED_NUTRITION_DATABASE.value,
                source_ref="usda_fdc:999",
                calories=300.0,
            ),
        ),
    )
    assessment = smoke.assess_fixture(spec, outcome)
    assert not assessment.passed
    assert any("forbidden source" in f for f in assessment.failures)


def test_dehydrated_banana_caught_by_calorie_band() -> None:
    # A "100 grams banana" that costs as banana powder (~346 kcal) breaks the band.
    spec = _spec(key="100g-banana", total_kcal_low=50.0, total_kcal_high=160.0)
    outcome = smoke.FixtureOutcome(
        status="completed", items=(_item(name="banana", calories=346.0),)
    )
    assessment = smoke.assess_fixture(spec, outcome)
    assert not assessment.passed
    assert any("outside the plausible band" in f for f in assessment.failures)


def test_forbidden_form_substring_in_source_ref_fails() -> None:
    spec = _spec(forbid_substrings=("powder",))
    outcome = smoke.FixtureOutcome(
        status="completed",
        items=(_item(name="banana", source_label="Banana powder, dehydrated", calories=105.0),),
    )
    assessment = smoke.assess_fixture(spec, outcome)
    assert not assessment.passed
    assert any("forbidden form 'powder'" in f for f in assessment.failures)


def test_silent_zero_calorie_item_fails() -> None:
    outcome = smoke.FixtureOutcome(status="completed", items=(_item(calories=0.0),))
    assessment = smoke.assess_fixture(_spec(), outcome)
    assert not assessment.passed
    assert any("no positive calories" in f for f in assessment.failures)


def test_missing_provenance_fails() -> None:
    outcome = smoke.FixtureOutcome(
        status="completed", items=(_item(source_type=None, source_ref=None, source_label=None),)
    )
    assessment = smoke.assess_fixture(_spec(), outcome)
    assert not assessment.passed
    assert any("no source provenance" in f for f in assessment.failures)


def test_wrong_item_count_fails() -> None:
    spec = _spec(expected_item_count=2)
    outcome = smoke.FixtureOutcome(status="completed", items=(_item(),))
    assessment = smoke.assess_fixture(spec, outcome)
    assert not assessment.passed
    assert any("expected 2 derived item(s)" in f for f in assessment.failures)


def test_absurd_calories_fail_per_item_ceiling() -> None:
    spec = _spec(total_kcal_low=0.0, total_kcal_high=1e9)
    outcome = smoke.FixtureOutcome(
        status="completed", items=(_item(calories=smoke.PER_ITEM_ABSURD_KCAL + 1),)
    )
    assessment = smoke.assess_fixture(spec, outcome)
    assert not assessment.passed
    assert any("plausibility ceiling" in f for f in assessment.failures)


# --------------------------------------------------------------------------- #
# Fixture set integrity
# --------------------------------------------------------------------------- #


def test_all_story_fixtures_are_present() -> None:
    raw_texts = {f.raw_text for f in smoke.FIXTURES}
    assert "one banana" in raw_texts
    assert "2 large eggs" in raw_texts
    assert "1 slice wheat toast" in raw_texts
    assert "two scrambled eggs and one slice buttered toast" in raw_texts
    assert "100 grams banana" in raw_texts
    assert "compliments brand chicken strips (i had 4)" in raw_texts
    # The 2026-07-10 live failure, exact phrase.
    assert any("toppables brand crackers" in t and "dill pickle hummus" in t for t in raw_texts)


def test_load_fixtures_parses_data_file(tmp_path: Path) -> None:
    data = {
        "fixtures": [
            {
                "key": "k",
                "raw_text": "one banana",
                "expected_item_count": 1,
                "total_kcal_low": 50.0,
                "total_kcal_high": 200.0,
                "forbid_source_types": ["trusted_nutrition_database"],
                "forbid_substrings": ["powder"],
            },
            {
                "key": "any",
                "raw_text": "some milk",
                "expected_item_count": None,
                "total_kcal_low": 0.0,
                "total_kcal_high": 500.0,
            },
        ]
    }
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    fixtures = smoke.load_fixtures(path)
    assert len(fixtures) == 2
    assert fixtures[0].forbid_source_types == (SourceType.TRUSTED_NUTRITION_DATABASE,)
    assert fixtures[0].forbid_substrings == ("powder",)
    # A null expected_item_count means "at least one".
    assert fixtures[1].expected_item_count is None
    assert fixtures[1].forbid_source_types == ()


def test_shipped_fixture_data_file_loads() -> None:
    # The real data file the smoke ships loads and covers every story fixture.
    assert len(smoke.load_fixtures()) == len(smoke.FIXTURES) == 7


def test_branded_snack_fixture_expects_two_items() -> None:
    snack = next(f for f in smoke.FIXTURES if f.key == "branded-crackers-and-hummus")
    assert snack.expected_item_count == 2


def test_compliments_fixture_forbids_generic_fdc() -> None:
    fixture = next(f for f in smoke.FIXTURES if f.key == "compliments-chicken-strips")
    assert SourceType.TRUSTED_NUTRITION_DATABASE in fixture.forbid_source_types


# --------------------------------------------------------------------------- #
# Item extraction + output redaction
# --------------------------------------------------------------------------- #


def test_extract_items_maps_source_and_calories() -> None:
    items = smoke._extract_items(
        [
            {
                "name": "white rice",
                "calories": 205.0,
                "source": {
                    "source_type": "trusted_nutrition_database",
                    "label": "USDA",
                    "ref": "usda_fdc:168880",
                },
            }
        ]
    )
    assert len(items) == 1
    assert items[0].name == "white rice"
    assert items[0].source_type == "trusted_nutrition_database"
    assert items[0].calories == 205.0


def test_extract_items_tolerates_missing_source() -> None:
    items = smoke._extract_items([{"name": "mystery", "calories": None, "source": None}])
    assert items[0].source_type is None
    assert items[0].calories is None


def test_format_assessment_prints_only_sanitized_fields() -> None:
    spec = _spec(key="banana", raw_text="one banana")
    outcome = smoke.FixtureOutcome(
        status="completed",
        items=(_item(name="banana", calories=105.0),),
    )
    lines = smoke.format_assessment(smoke.assess_fixture(spec, outcome))
    joined = "\n".join(lines)
    assert "[PASS] banana" in joined
    assert "banana — trusted_nutrition_database usda_fdc:123 — 105 kcal" in joined
    # A token/password must never appear in formatted output.
    assert "Bearer" not in joined
    assert smoke._FIXTURE_PASSWORD not in joined


def test_format_assessment_shows_failures_and_clarification() -> None:
    outcome = smoke.FixtureOutcome(
        status="needs_clarification",
        items=(),
        clarification_texts=("How much banana did you have?",),
    )
    lines = smoke.format_assessment(smoke.assess_fixture(_spec(), outcome))
    joined = "\n".join(lines)
    assert "[FAIL]" in joined
    assert "? clarification: How much banana did you have?" in joined
    assert "! expected 'completed'" in joined

"""FDC common-food candidate ranking tests (FTY-254).

Unit-level: the lexical compatibility/preference policy in
:mod:`app.estimator.fdc_ranking`. Client-level: :meth:`FdcClient.lookup` against
fake FDC result lists (network-free transport), proving the resolver's selected
match — and its recorded provenance — is the compatible common form, not USDA's
first lexical hit. Nutrient values are public USDA FDC figures (SR Legacy /
Foundation per-100g), synthetic fixtures otherwise.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from app.estimator.fdc import FdcClient, FdcSettings
from app.estimator.fdc_ranking import (
    fdc_preference_key,
    is_fdc_description_compatible,
    is_fdc_description_rank_stable,
)

# ---------------------------------------------------------------------------
# Compatibility gate
# ---------------------------------------------------------------------------

_PICKLES_ROW = "Pickles, cucumber, dill or kosher dill"


@pytest.mark.parametrize(
    ("query", "description"),
    [
        # Head-noun/category mismatch: the food identity is hummus; a pickles row
        # matching only the flavor tokens is a different food (the FTY-254 audit).
        ("dill pickle hummus", _PICKLES_ROW),
        ("hummus", _PICKLES_ROW),
        # Density-changing forms the query did not state.
        ("banana", "Bananas, dehydrated, or banana powder"),
        ("milk", "Milk, dry, whole, with added vitamin D"),
        ("apricots", "Apricots, dried, sulfured, uncooked"),
        ("potato", "Potato flour"),
        ("banana", "Snacks, banana chips"),
        ("banana", "Babyfood, fruit, bananas with tapioca, strained"),
        ("banana", "Babyfoods, fruit, bananas with tapioca, strained"),
        # Stating one form opts into that form only, never a different one:
        # chips are not the dehydrated/powder form, condensed is not dry.
        ("banana chips", "Bananas, dehydrated, or banana powder"),
        ("condensed milk", "Milk, dry, whole, with added vitamin D"),
        # Query-side "dry roasted" is a preparation idiom, not a stated
        # dehydrated/dried/powdered form: it opts into no density change.
        ("dry roasted peanuts", "Peanuts, dehydrated"),
        ("dry roasted bananas", "Bananas, dehydrated, or banana powder"),
        # A stated added ingredient the row does not carry: plain toast facts
        # materially undercount buttered toast.
        ("buttered toast", "Bread, white, commercially prepared, toasted"),
    ],
)
def test_incompatible_descriptions_are_rejected(query: str, description: str) -> None:
    assert is_fdc_description_compatible(query, description) is False


@pytest.mark.parametrize(
    ("query", "description"),
    [
        # Plain "dill pickle" IS a pickle food: the same row stays eligible.
        ("dill pickle", _PICKLES_ROW),
        ("dill pickles", _PICKLES_ROW),
        ("banana", "Bananas, ripe and slightly ripe, raw"),
        ("hummus", "Hummus, commercial"),
        # A query stating the processed form opts into it, including the same
        # form's synonym-family tokens in one description ("dehydrated, or
        # banana powder" names one form two ways).
        ("banana powder", "Bananas, dehydrated, or banana powder"),
        ("dried banana", "Bananas, dehydrated, or banana powder"),
        ("dried apricots", "Apricots, dried, sulfured, uncooked"),
        ("dry milk", "Milk, dry, whole, with added vitamin D"),
        # Participle/plural variants still name the head noun.
        ("wheat toast", "Bread, whole-wheat, commercially prepared, toasted"),
        ("scrambled eggs", "Egg, whole, cooked, scrambled"),
        ("eggs", "Eggs, Grade A, Large, egg whole"),
        # An added-ingredient query token present in the row keeps it eligible.
        ("buttered toast", "Bread, toasted, with butter"),
        # "dry roasted" is a benign preparation idiom, not a dehydrated form —
        # on the description side and on the query side alike.
        ("peanuts", "Peanuts, all types, dry-roasted, with salt"),
        ("dry roasted peanuts", "Peanuts, all types, dry-roasted, with salt"),
        ("dry roasted peanuts", "Peanuts, all types, raw"),
        # Demoted forms stay *eligible* (preference-ordered, not rejected).
        ("tuna", "Fish, tuna, light, canned in water, drained solids"),
        # Nothing to verify: an empty description cannot be proven foreign.
        ("banana", ""),
    ],
)
def test_compatible_descriptions_stay_eligible(query: str, description: str) -> None:
    assert is_fdc_description_compatible(query, description) is True


# ---------------------------------------------------------------------------
# Preference ordering among compatible rows
# ---------------------------------------------------------------------------


def test_query_token_coverage_prefers_the_stated_preparation() -> None:
    scrambled = fdc_preference_key("scrambled eggs", "Egg, whole, cooked, scrambled")
    raw = fdc_preference_key("scrambled eggs", "Eggs, Grade A, Large, egg whole")
    assert scrambled < raw


def test_unstated_demoted_form_ranks_below_the_plain_form() -> None:
    fresh = fdc_preference_key("tuna", "Fish, tuna, fresh, bluefin, raw")
    canned = fdc_preference_key("tuna", "Fish, tuna, light, canned in water, drained solids")
    assert fresh < canned


def test_stated_demoted_form_is_not_penalized() -> None:
    canned = fdc_preference_key("canned tuna", "Fish, tuna, light, canned in water")
    fresh = fdc_preference_key("canned tuna", "Fish, tuna, fresh, bluefin, raw")
    assert canned < fresh


def test_rank_stable_cache_rows_must_have_no_demotions_and_full_query_coverage() -> None:
    assert is_fdc_description_rank_stable("tuna", "Fish, tuna, fresh, bluefin, raw") is True
    assert is_fdc_description_rank_stable("tuna", "Fish, tuna, light, canned in water") is False
    assert is_fdc_description_rank_stable("scrambled eggs", "Egg, whole, raw, fresh") is False
    assert is_fdc_description_rank_stable("scrambled eggs", "Egg, whole, cooked, scrambled") is True


# ---------------------------------------------------------------------------
# Client-level ranking with fake FDC result lists
# ---------------------------------------------------------------------------


def _fdc_food(
    fdc_id: int,
    description: str,
    calories: float,
    *,
    protein: float = 1.0,
    carbs: float = 10.0,
    fat: float = 0.5,
    serving_g: float | None = None,
) -> dict[str, Any]:
    food: dict[str, Any] = {
        "fdcId": fdc_id,
        "description": description,
        "foodNutrients": [
            {"nutrientId": 1008, "value": calories},
            {"nutrientId": 1003, "value": protein},
            {"nutrientId": 1005, "value": carbs},
            {"nutrientId": 1004, "value": fat},
        ],
    }
    if serving_g is not None:
        food["servingSize"] = serving_g
        food["servingSizeUnit"] = "g"
    return food


#: Public USDA SR Legacy per-100g values: dehydrated banana 346 kcal, raw 89 kcal.
_BANANA_RESPONSE: dict[str, Any] = {
    "foods": [
        _fdc_food(9041, "Bananas, dehydrated, or banana powder", 346.0, carbs=88.3),
        _fdc_food(3110, "Babyfoods, fruit, bananas with tapioca, strained", 91.0, carbs=21.3),
        _fdc_food(9040, "Bananas, raw", 89.0, carbs=22.8),
    ]
}


def _client(reply: dict[str, Any]) -> FdcClient:
    def transport(url: str, **kwargs: Any) -> dict[str, Any]:
        return reply

    return FdcClient(FdcSettings(api_key=SecretStr("test-key")), transport=transport)


def test_lookup_skips_dehydrated_banana_for_a_plain_banana_query() -> None:
    facts = _client(_BANANA_RESPONSE).lookup("banana")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:9040"
    assert facts.facts.calories == pytest.approx(89.0)


def test_lookup_skips_plural_babyfoods_banana_for_a_plain_banana_query() -> None:
    response = {
        "foods": [
            _fdc_food(
                3110,
                "Babyfoods, fruit, bananas with tapioca, strained",
                91.0,
                carbs=21.3,
            ),
            _fdc_food(9040, "Bananas, raw", 89.0, carbs=22.8),
        ]
    }

    facts = _client(response).lookup("banana")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:9040"
    assert facts.facts.calories == pytest.approx(89.0)


def test_lookup_selects_dehydrated_banana_when_the_query_states_the_form() -> None:
    facts = _client(_BANANA_RESPONSE).lookup("banana powder")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:9041"
    assert facts.facts.calories == pytest.approx(346.0)


def test_lookup_misses_cleanly_when_no_row_names_the_head_noun() -> None:
    """The Toppables/PC hummus audit: a pickles-only result list is a miss."""

    pickles_only = {"foods": [_fdc_food(11937, _PICKLES_ROW, 11.0, serving_g=65.0)]}

    assert _client(pickles_only).lookup("dill pickle hummus") is None


def test_lookup_still_resolves_plain_dill_pickle_to_the_pickles_row() -> None:
    pickles_only = {"foods": [_fdc_food(11937, _PICKLES_ROW, 11.0, serving_g=65.0)]}

    facts = _client(pickles_only).lookup("dill pickle")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:11937"
    assert facts.default_serving_g == pytest.approx(65.0)


def test_lookup_prefers_the_stated_preparation_over_relevance_order() -> None:
    response = {
        "foods": [
            _fdc_food(1123, "Egg, whole, raw, fresh", 143.0, protein=12.6, fat=9.5),
            _fdc_food(1132, "Egg, whole, cooked, scrambled", 149.0, protein=10.0, fat=11.0),
        ]
    }

    facts = _client(response).lookup("scrambled eggs")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:1132"


def test_lookup_prefers_plain_form_over_unstated_canned_form() -> None:
    response = {
        "foods": [
            _fdc_food(15121, "Fish, tuna, light, canned in water", 116.0, protein=25.5, fat=0.8),
            _fdc_food(15076, "Fish, tuna, fresh, bluefin, raw", 144.0, protein=23.3, fat=4.9),
        ]
    }

    facts = _client(response).lookup("tuna")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:15076"


def test_lookup_keeps_demoted_form_when_it_is_the_only_compatible_row() -> None:
    response = {
        "foods": [
            _fdc_food(15121, "Fish, tuna, light, canned in water", 116.0, protein=25.5, fat=0.8),
        ]
    }

    facts = _client(response).lookup("tuna")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:15121"


def test_lookup_falls_back_to_relevance_order_between_equal_rows() -> None:
    response = {
        "foods": [
            _fdc_food(1, "Bananas, raw", 89.0),
            _fdc_food(2, "Bananas, ripe and slightly ripe, raw", 98.0),
        ]
    }

    facts = _client(response).lookup("banana")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:1"


def test_list_matches_still_surfaces_every_energy_bearing_alternative() -> None:
    """Re-match (FTY-093) deliberately lists all alternatives, unranked."""

    matches = _client(_BANANA_RESPONSE).list_matches("banana")

    assert [m.source_ref for m in matches] == ["usda_fdc:9041", "usda_fdc:3110", "usda_fdc:9040"]

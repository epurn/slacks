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
        # Extracted-fat "oil" form the query did not state (FTY-418): a plain
        # "mustard" must not cost as mustard oil (884 kcal/100g of pure fat).
        ("mustard", "Oil, mustard"),
        ("peanut", "Oil, peanut, salad or cooking"),
        ("coconut", "Oil, coconut"),
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
        # A query that states the oil keeps the oil row (FTY-418), exactly like
        # every other stated density-changing form.
        ("mustard oil", "Oil, mustard"),
        ("olive oil", "Oil, olive, extra virgin"),
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
# Part-of-food demotion (FTY-388): an unstated white/yolk/shell part never
# outranks a whole-food row, but a query stating the part keeps it.
# ---------------------------------------------------------------------------

#: The concrete poisoned-cache row: FDC 747997 "egg white" (~55 kcal/100g).
_EGG_WHITE_ROW = "Eggs, Grade A, Large, egg white"
#: The compatible whole-egg row that ties it on query-token coverage.
_EGG_WHOLE_ROW = "Eggs, Grade A, Large, egg whole"


@pytest.mark.parametrize(
    "query",
    ["large eggs", "eggs", "egg"],
)
def test_part_of_food_row_stays_gate_compatible(query: str) -> None:
    # The demotion is a preference-order signal, not a rejection: the egg-white
    # row still passes the compatibility gate (head noun present, no rejected
    # form), so the reported coverage tie is genuinely between two eligible rows.
    assert is_fdc_description_compatible(query, _EGG_WHITE_ROW) is True
    assert is_fdc_description_compatible(query, _EGG_WHOLE_ROW) is True


def test_unstated_part_row_ranks_below_the_whole_food_row_on_a_coverage_tie() -> None:
    # Both rows are gate-compatible and cover both query tokens (large, eggs);
    # the part-of-food term breaks the tie for the whole-egg row.
    whole = fdc_preference_key("large eggs", _EGG_WHOLE_ROW)
    white = fdc_preference_key("large eggs", _EGG_WHITE_ROW)
    assert whole < white


@pytest.mark.parametrize(
    ("query", "description"),
    [
        ("egg whites", _EGG_WHITE_ROW),  # plural query token, singular row token
        ("egg white", _EGG_WHITE_ROW),
        ("2 egg yolks", "Egg, yolk, raw, fresh"),
        ("egg shell", "Egg, shell, dried"),
    ],
)
def test_stated_part_is_not_demoted(query: str, description: str) -> None:
    # A query that names the part is exempt: the part token contributes no
    # demotion, so its preference key has a zero part-of-food term.
    assert fdc_preference_key(query, description)[0] == 0


def test_unstated_part_leads_the_preference_key() -> None:
    # An unstated part outweighs an unstated demoted form and higher coverage:
    # a whole (frozen) egg is closer in calorie identity than an egg white.
    whole_frozen = fdc_preference_key("eggs", "Eggs, whole, frozen")
    white = fdc_preference_key("eggs", _EGG_WHITE_ROW)
    assert whole_frozen < white


def test_unstated_part_row_is_never_rank_stable() -> None:
    # The poisoned-cache self-heal hinges on this: an egg-white cache row for a
    # whole-egg query is compatible but NOT rank-stable, so it re-fetches.
    assert is_fdc_description_rank_stable("large eggs", _EGG_WHITE_ROW) is False
    assert is_fdc_description_rank_stable("eggs", _EGG_WHITE_ROW) is False
    # A whole-egg row with full coverage stays rank-stable (served from cache).
    assert is_fdc_description_rank_stable("large eggs", _EGG_WHOLE_ROW) is True
    # A query that states the part keeps the part row rank-stable.
    assert is_fdc_description_rank_stable("egg whites", _EGG_WHITE_ROW) is True


# ---------------------------------------------------------------------------
# Identity-shifting-modifier demotion (FTY-424): an unstated leaf/green/seed or
# cabbage-family sense never outranks a plain compatible row, but a query stating
# the modifier keeps it, and a category-led row is never rejected.
# ---------------------------------------------------------------------------

#: The reported live set for bare "mustard": the everyday condiment plus three
#: identity-shifting senses, all naming the head noun "mustard".
_MUSTARD_PREPARED_ROW = "Mustard, prepared, yellow"
_CABBAGE_MUSTARD_ROW = "Cabbage, mustard, salted"
_MUSTARD_GREENS_ROW = "Mustard greens, raw"
_MUSTARD_SEED_ROW = "Mustard seed, yellow"


@pytest.mark.parametrize(
    "description",
    [_MUSTARD_PREPARED_ROW, _CABBAGE_MUSTARD_ROW, _MUSTARD_GREENS_ROW, _MUSTARD_SEED_ROW],
)
def test_identity_shifting_rows_stay_gate_compatible(description: str) -> None:
    # The demotion is a preference-order signal, not a rejection: every row still
    # passes the head-noun compatibility gate ("mustard" is present in all four),
    # so the reported tie is genuinely between eligible rows.
    assert is_fdc_description_compatible("mustard", description) is True


@pytest.mark.parametrize(
    "description",
    [_CABBAGE_MUSTARD_ROW, _MUSTARD_GREENS_ROW, _MUSTARD_SEED_ROW],
)
def test_unstated_identity_shift_ranks_below_the_prepared_row(description: str) -> None:
    prepared = fdc_preference_key("mustard", _MUSTARD_PREPARED_ROW)
    shifted = fdc_preference_key("mustard", description)
    assert prepared < shifted
    # The everyday condiment carries no unstated identity modifier at all.
    assert prepared[0] == 0
    assert shifted[0] >= 1


@pytest.mark.parametrize(
    ("query", "description"),
    [
        ("mustard greens", _MUSTARD_GREENS_ROW),  # plural-safe: greens ↔ green
        ("mustard green", _MUSTARD_GREENS_ROW),
        ("mustard seed", _MUSTARD_SEED_ROW),
        ("mustard seeds", _MUSTARD_SEED_ROW),
    ],
)
def test_stated_identity_modifier_is_not_demoted(query: str, description: str) -> None:
    # A query that names the modifier is exempt through the same variant rule the
    # part-of-food check uses: the identity term contributes no demotion.
    assert fdc_preference_key(query, description)[0] == 0


@pytest.mark.parametrize(
    ("query", "description"),
    [
        ("salmon", "Fish, salmon, Atlantic, farmed, cooked"),
        ("mozzarella", "Cheese, mozzarella, whole milk"),
    ],
)
def test_leading_category_rows_are_not_identity_demoted(query: str, description: str) -> None:
    # The fix is a modifier vocabulary, NOT a head-noun-position gate: a
    # category-led description names no identity-shifting modifier, so it stays
    # compatible and un-demoted (its identity term is zero).
    assert is_fdc_description_compatible(query, description) is True
    assert fdc_preference_key(query, description)[0] == 0


def test_identity_shifting_row_is_never_rank_stable() -> None:
    # A greens/seed/cabbage cache row for a bare "mustard" query is compatible but
    # NOT rank-stable, so it re-fetches to the prepared row (self-heal like FTY-388).
    assert is_fdc_description_rank_stable("mustard", _MUSTARD_GREENS_ROW) is False
    assert is_fdc_description_rank_stable("mustard", _MUSTARD_SEED_ROW) is False
    assert is_fdc_description_rank_stable("mustard", _CABBAGE_MUSTARD_ROW) is False
    # A query that states the modifier keeps its row rank-stable.
    assert is_fdc_description_rank_stable("mustard greens", _MUSTARD_GREENS_ROW) is True


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


#: Public USDA figures: "Oil, mustard" 884 kcal/100g (pure fat); "Mustard,
#: prepared, yellow" ~60 kcal/100g. FTY-418 wrong-variant regression fixture.
_MUSTARD_RESPONSE: dict[str, Any] = {
    "foods": [
        _fdc_food(172337, "Oil, mustard", 884.0, protein=0.0, carbs=0.0, fat=100.0),
        _fdc_food(172234, "Mustard, prepared, yellow", 60.0, protein=3.7, carbs=5.3, fat=3.4),
    ]
}


def test_lookup_skips_mustard_oil_for_a_plain_mustard_query() -> None:
    # FTY-418: a bare "mustard" landed on "Oil, mustard" (884 kcal/100g), so 15 g
    # costed at 132.6 kcal — ~13x real prepared mustard. The oil form is now
    # rejected, so the compatible prepared-mustard row backs the resolution.
    facts = _client(_MUSTARD_RESPONSE).lookup("mustard")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:172234"
    assert facts.facts.calories == pytest.approx(60.0)
    # The macros come with it — never the oil row's 0 protein / 0 carbs.
    assert facts.facts.protein_g == pytest.approx(3.7)


def test_lookup_keeps_mustard_oil_when_the_query_states_the_oil() -> None:
    facts = _client(_MUSTARD_RESPONSE).lookup("mustard oil")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:172337"
    assert facts.facts.calories == pytest.approx(884.0)


#: The full reported live candidate set for bare "mustard" (FTY-424): the
#: prepared condiment plus the cabbage-family, greens, and seed senses — all
#: passing the head-noun gate, so the compatibility gate alone cannot separate
#: them. Public USDA per-100g figures: prepared ~60, cabbage-mustard ~28, greens
#: ~27, seed ~508 kcal. FTY-418's oil row is not in this post-oil-fix set.
_MUSTARD_IDENTITY_RESPONSE: dict[str, Any] = {
    "foods": [
        _fdc_food(169891, _CABBAGE_MUSTARD_ROW, 28.0, protein=2.5, carbs=5.0, fat=0.4),
        _fdc_food(11270, _MUSTARD_GREENS_ROW, 27.0, protein=2.9, carbs=4.7, fat=0.4),
        _fdc_food(172232, _MUSTARD_SEED_ROW, 508.0, protein=26.1, carbs=28.1, fat=36.2),
        _fdc_food(172234, _MUSTARD_PREPARED_ROW, 60.0, protein=3.7, carbs=5.3, fat=3.4),
    ]
}


def test_lookup_selects_prepared_mustard_over_identity_shifting_rows() -> None:
    # FTY-424: after the oil form is gone (FTY-418), a bare "mustard" landed on
    # "Cabbage, mustard, salted" (usda_fdc:169891) — sane calories but the wrong
    # identity (a leafy-green pickle). All four rows pass the head-noun gate; the
    # identity-shifting-modifier demotion lands the prepared condiment row.
    facts = _client(_MUSTARD_IDENTITY_RESPONSE).lookup("mustard")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:172234"
    assert facts.facts.calories == pytest.approx(60.0)
    assert facts.facts.protein_g == pytest.approx(3.7)


def test_lookup_keeps_mustard_greens_when_the_query_states_the_modifier() -> None:
    facts = _client(_MUSTARD_IDENTITY_RESPONSE).lookup("mustard greens")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:11270"
    assert facts.facts.calories == pytest.approx(27.0)


def test_lookup_keeps_mustard_seed_when_the_query_states_the_modifier() -> None:
    facts = _client(_MUSTARD_IDENTITY_RESPONSE).lookup("mustard seed")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:172232"
    assert facts.facts.calories == pytest.approx(508.0)


def test_lookup_leaves_leading_category_rows_unaffected_by_the_modifier_vocab() -> None:
    # The explicit unsafe alternative (a leading-category gate) is off the table:
    # a category-led description still resolves for its bare head-noun query.
    salmon = {
        "foods": [_fdc_food(175168, "Fish, salmon, Atlantic, farmed, cooked", 206.0)],
    }
    mozzarella = {
        "foods": [_fdc_food(1026, "Cheese, mozzarella, whole milk", 300.0)],
    }

    salmon_facts = _client(salmon).lookup("salmon")
    mozzarella_facts = _client(mozzarella).lookup("mozzarella")

    assert salmon_facts is not None
    assert salmon_facts.source_ref == "usda_fdc:175168"
    assert mozzarella_facts is not None
    assert mozzarella_facts.source_ref == "usda_fdc:1026"


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


def test_lookup_prefers_the_whole_egg_over_the_egg_white_on_a_relevance_tie() -> None:
    """FTY-388: the poisoned tie — FDC lists the egg-white row first for
    ``large eggs`` and it ties the whole-egg row on coverage. The whole-food row
    must win, so the entry costs ~143 kcal/100g (2 × 50 g ≈ 143 kcal), not 55."""

    response = {
        "foods": [
            _fdc_food(747997, _EGG_WHITE_ROW, 55.0, protein=11.0, carbs=0.7, fat=0.2),
            _fdc_food(748967, _EGG_WHOLE_ROW, 143.0, protein=12.6, carbs=0.7, fat=9.5),
        ]
    }

    facts = _client(response).lookup("large eggs")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:748967"
    assert facts.facts.calories == pytest.approx(143.0)


def test_lookup_keeps_the_egg_white_when_the_query_states_the_part() -> None:
    """The stated-token exemption: ``2 egg whites`` still resolves to the
    egg-white row even when a whole-egg row is also returned."""

    response = {
        "foods": [
            _fdc_food(748967, _EGG_WHOLE_ROW, 143.0, protein=12.6, carbs=0.7, fat=9.5),
            _fdc_food(747997, _EGG_WHITE_ROW, 55.0, protein=11.0, carbs=0.7, fat=0.2),
        ]
    }

    facts = _client(response).lookup("egg whites")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:747997"
    assert facts.facts.calories == pytest.approx(55.0)


def test_lookup_keeps_the_egg_white_when_it_is_the_only_compatible_row() -> None:
    """Demotion, not rejection: a lone part row still resolves (like canned tuna
    for ``tuna``) — the whole-food row simply wins when both are present."""

    response = {"foods": [_fdc_food(747997, _EGG_WHITE_ROW, 55.0, protein=11.0, fat=0.2)]}

    facts = _client(response).lookup("large eggs")

    assert facts is not None
    assert facts.source_ref == "usda_fdc:747997"


def test_list_matches_still_surfaces_every_energy_bearing_alternative() -> None:
    """Re-match (FTY-093) deliberately lists all alternatives, unranked."""

    matches = _client(_BANANA_RESPONSE).list_matches("banana")

    assert [m.source_ref for m in matches] == ["usda_fdc:9041", "usda_fdc:3110", "usda_fdc:9040"]

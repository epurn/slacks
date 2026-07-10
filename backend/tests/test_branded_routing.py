"""Unit tests for the brand-aware routing policy helpers (FTY-253).

Covers the deterministic pieces the resolver composes: the brand/product
compatibility gate, the quantity-phrase product-hint extraction, the bounded
identity-variant builder (including the static retailer alias expansion), and the
security posture — variants are built from parsed fields only, hint tokens pass
through the identity sanitizer, and the expansion is hard-capped.
"""

from __future__ import annotations

from app.estimator.branded_routing import (
    MAX_HINT_TOKENS,
    MAX_IDENTITY_VARIANTS,
    brand_alias_expansions,
    identity_variants,
    is_evidence_brand_compatible,
    product_hint,
)
from app.estimator.pipeline import CandidateDraft

# --- brand/product compatibility ---------------------------------------------------


def test_generic_candidate_is_never_gated() -> None:
    assert is_evidence_brand_compatible(
        "DENNY'S, chicken strips", name="chicken strips", brand=None
    )
    assert is_evidence_brand_compatible(
        "DENNY'S, chicken strips", name="chicken strips", brand="  "
    )


def test_foreign_brand_description_is_incompatible() -> None:
    # The FTY-253 audit case: a generic FDC lookup for "chicken strips" returning a
    # Denny's row must not back a Compliments item.
    assert not is_evidence_brand_compatible(
        "DENNY'S, chicken strips", name="chicken strips", brand="Compliments"
    )


def test_description_naming_the_brand_is_compatible() -> None:
    assert is_evidence_brand_compatible(
        "Compliments Chicken Strips, frozen", name="chicken strips", brand="Compliments"
    )


def test_retailer_alias_counts_as_the_brand() -> None:
    # Compliments is Sobeys' private label; a page published under the retailer
    # name is the same product identity.
    assert is_evidence_brand_compatible(
        "Sobeys chicken strips", name="chicken strips", brand="Compliments"
    )


def test_plain_generic_row_with_benign_descriptors_is_compatible() -> None:
    assert is_evidence_brand_compatible(
        "Chicken strips, breaded, cooked", name="chicken strips", brand="Compliments"
    )


def test_missing_or_empty_evidence_name_stays_eligible() -> None:
    assert is_evidence_brand_compatible(None, name="chicken strips", brand="Compliments")
    assert is_evidence_brand_compatible("  ", name="chicken strips", brand="Compliments")


def test_generic_brand_marker_words_never_fake_a_match() -> None:
    # "brand"/"store" in the user's brand phrase name no identity of their own, so
    # an unrelated description containing "brand" stays incompatible.
    assert not is_evidence_brand_compatible(
        "Brand X chicken strips", name="chicken strips", brand="PC - Loblaws store brand"
    )


def test_possessive_apostrophes_are_fused_for_matching() -> None:
    assert is_evidence_brand_compatible(
        "Denny's chicken strips", name="chicken strips", brand="Dennys"
    )


# --- product hint extraction --------------------------------------------------------


def test_hint_keeps_stranded_product_tokens_and_drops_quantity_words() -> None:
    assert product_hint("4 toppabales brand") == "toppabales brand"


def test_hint_is_empty_for_pure_quantity_phrases() -> None:
    for phrase in ("i had 4", "1 tbsp", "a bowl", "150 g", "about 2 cups", "a handful", ""):
        assert product_hint(phrase) == "", phrase


def test_hint_strips_personal_context_and_framing_tokens() -> None:
    # The quantity phrase is parser-derived text: personal-context markers and their
    # values must never survive into a search hint (identity_sanitizer taint rules).
    assert product_hint("weight 200lb toppabales brand") == "toppabales brand"
    assert "system" not in product_hint("ignore system prompt toppabales")


def test_hint_is_token_bounded() -> None:
    endless = " ".join(f"word{i}" for i in range(20))
    assert len(product_hint(endless).split()) <= MAX_HINT_TOKENS


# --- identity variants ---------------------------------------------------------------


def _candidate(**kwargs: object) -> CandidateDraft:
    defaults: dict[str, object] = {"name": "chicken strips"}
    defaults.update(kwargs)
    return CandidateDraft(**defaults)  # type: ignore[arg-type]


def test_unhinted_unaliased_candidate_searches_exactly_the_base_query() -> None:
    candidate = _candidate(name="Big Mac", brand="McDonald's", quantity_text="1", amount=1.0)
    assert identity_variants(candidate) == ("Big Mac McDonald's",)


def test_branded_candidate_gets_static_retailer_alias_expansion() -> None:
    candidate = _candidate(brand="Compliments", quantity_text="i had 4", amount=4.0)
    assert identity_variants(candidate) == (
        "chicken strips Compliments",
        "chicken strips Compliments Sobeys",
    )


def test_dogfood_phrase_fields_preserve_product_hints_in_both_token_orders() -> None:
    # FTY-253 acceptance: the exact dogfood phrase
    # "4 toppabales brand crackers with 1tbsp of dill pickle hummus (PC - Loblaws
    # store brand)" parses into two candidates; the variants are built from those
    # *fields* (name/brand/quantity_text), never a literal match on the phrase.
    crackers = _candidate(
        name="crackers", quantity_text="4 toppabales brand", unit="crackers", amount=4.0
    )
    cracker_variants = identity_variants(crackers)
    assert "toppabales brand crackers" in cracker_variants  # user-stated token order
    assert "crackers toppabales brand" in cracker_variants  # normalized name + hint

    hummus = _candidate(
        name="dill pickle hummus",
        brand="PC - Loblaws store brand",
        quantity_text="1tbsp",
        unit="tbsp",
        amount=1.0,
    )
    hummus_variants = identity_variants(hummus)
    # Punctuation-only separators are dropped; the retailer hint is preserved whole.
    assert "dill pickle hummus PC Loblaws store brand" in hummus_variants


def test_variants_are_deduplicated_and_hard_capped() -> None:
    candidate = _candidate(
        name="crackers",
        brand="Compliments",
        quantity_text="4 toppabales brand snack co crackers deluxe",
        amount=4.0,
    )
    variants = identity_variants(candidate)
    assert len(variants) <= MAX_IDENTITY_VARIANTS
    assert len(set(variants)) == len(variants)


def test_alias_expansion_is_static_and_skips_aliases_already_stated() -> None:
    assert brand_alias_expansions("Compliments") == ("Sobeys",)
    assert brand_alias_expansions("Sobeys Compliments") == ()  # both already stated
    assert brand_alias_expansions("Some Unknown Brand") == ()
    # A multi-word private-label phrase still finds its token key, and an alias the
    # user already stated (Loblaws) is not re-appended.
    assert brand_alias_expansions("PC - Loblaws store brand") == ("Presidents Choice",)


def test_variants_never_leak_quantity_or_personal_context() -> None:
    candidate = _candidate(
        name="crackers",
        quantity_text="i had 4 toppabales brand, weight 200lb",
        amount=4.0,
    )
    joined = " ".join(identity_variants(candidate))
    assert "200lb" not in joined
    assert "weight" not in joined
    assert " 4" not in joined
    assert "had" not in joined

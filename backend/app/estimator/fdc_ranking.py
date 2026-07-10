"""Common-food USDA FDC candidate ranking (FTY-254).

Deterministic, bounded lexical policy for choosing which FDC search result may
back a **generic/common** food candidate. The FTY-044 resolver took the first
energy-bearing result, which let USDA's search relevance pick the food's *form*:
``banana`` resolved to ``Bananas, dehydrated, or banana powder`` (346 kcal/100g)
and ``dill pickle hummus`` resolved to ``Pickles, cucumber, dill or kosher
dill`` — a trusted-database provenance wrapped around the wrong food. This
module makes ``trusted_nutrition_database`` mean *trusted nutrition facts for a
compatible food*, not a trusted lexical search hit:

- :func:`is_fdc_description_compatible` — whether one FDC row's description is
  the same food, in a compatible form, as the query. It rejects a row whose
  description misses the query's **head noun** (the food identity — ``hummus``
  in ``dill pickle hummus``; ``pickle`` is a flavor detail there, while plain
  ``dill pickle`` keeps ``pickle`` as the identity), a row carrying a
  **density-changing form** the user did not state (dehydrated / dried /
  powdered / flour / …), and a row missing an **added ingredient** the user
  stated (``buttered`` toast is not plain toast).
- :func:`fdc_preference_key` — orders the surviving compatible rows: prefer
  common/fresh/simple forms (fewest unstated demoted-form tokens such as
  ``canned``/``pickled``/``juice``), then the row covering more of the query's
  own tokens (``Egg, whole, cooked, scrambled`` beats ``Egg, whole, raw`` for
  ``scrambled eggs``), then USDA's original relevance order.

Everything here is pure string policy over the already-validated FDC
description — no I/O, no LLM, no user context. A query that rejects every row
is a clean source **miss**, so resolution falls forward to the
official/reference/model-prior tiers instead of committing the wrong food.
"""

from __future__ import annotations

import re
from typing import Final

#: Identity tokens: lower-cased alphanumeric runs (matches ``branded_routing``).
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")

#: Description forms whose energy density differs wildly from the plain food —
#: a dehydrated/powdered/flour/concentrated form is a *different food* for
#: calorie purposes (dehydrated banana is ~4x fresh). A row carrying one of
#: these tokens is rejected unless the query states that form itself
#: ("banana powder", "dried apricots"). A bounded documented tunable.
REJECTED_FORM_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "dehydrated",
        "dried",
        "powder",
        "powdered",
        "flour",
        "concentrate",
        "concentrated",
        "evaporated",
        "condensed",
        "chips",
        "crisps",
        "babyfood",
        "dry",
    }
)

#: ``dry`` is density-changing on its own ("Milk, dry, whole" is ~8x fluid
#: milk) but benign in the ``dry roasted`` preparation idiom (dry-roasted nuts
#: match raw-nut density). The idiom is excused on **both** sides: a
#: description's ``dry`` next to a roast marker keeps the row eligible, and a
#: query's ``dry`` next to a roast marker states a preparation, not the
#: dehydrated/dried/powdered form family — ``dry roasted peanuts`` must not
#: opt into a dehydrated row.
_DRY_ROASTED_MARKERS: Final[frozenset[str]] = frozenset({"roasted", "roast"})

#: Synonym families among the rejected form tokens: USDA names one processed
#: form several ways within a single row ("Bananas, dehydrated, or banana
#: powder"; "Milk, dry" is milk powder), so a query stating any token of a
#: family states that whole family. Families never bridge *different* processed
#: forms — ``chips`` does not state ``dehydrated``, ``condensed`` does not
#: state ``dry`` — so each unstated form still rejects the row on its own.
_REJECTED_FORM_FAMILIES: Final[tuple[frozenset[str], ...]] = (
    frozenset({"dehydrated", "dried", "dry", "powder", "powdered"}),
    frozenset({"chips", "crisps"}),
)

#: Description forms that keep the food recognizable but are less likely to be
#: what a plain query means — preferred *against*, not rejected, so they still
#: resolve when they are the only compatible row ("canned tuna" stays costable
#: for "tuna" when no fresh row is returned). A bounded documented tunable.
DEMOTED_FORM_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "canned",
        "pickled",
        "sweetened",
        "smoked",
        "cured",
        "frozen",
        "juice",
        "syrup",
    }
)

#: Query tokens naming an **added ingredient** the FDC row must also name for
#: its facts to cover the logged food: plain toast facts materially undercount
#: "buttered toast" (the butter is the point). A bounded documented tunable —
#: kept deliberately tiny; composite dishes are the rough-estimate tiers' job.
ADDED_INGREDIENT_QUERY_TOKENS: Final[frozenset[str]] = frozenset({"buttered"})


def _tokens(text: str) -> tuple[str, ...]:
    """Lower-cased alphanumeric identity tokens, in order."""

    return tuple(_TOKEN_RE.findall(text.lower()))


#: Suffix → replacement pairs generating a token's bounded surface variants.
_SUFFIX_VARIANTS: Final[tuple[tuple[str, str], ...]] = (
    ("ies", "y"),
    ("es", ""),
    ("s", ""),
    ("ed", ""),
    ("ed", "e"),
    ("ing", ""),
)

#: A stripped root shorter than this is noise, not a word stem.
_MIN_STEM_CHARS: Final[int] = 3


def _variants(token: str) -> frozenset[str]:
    """Bounded surface variants of ``token`` for singular/plural/participle matching.

    Two tokens denote the same word when their variant sets intersect:
    ``pickles`` ↔ ``pickle``, ``tomatoes`` ↔ ``tomato``, ``toasted`` ↔ ``toast``,
    ``buttered`` ↔ ``butter``, ``berries`` ↔ ``berry``. Deliberately naive — a
    false positive merely keeps a row eligible, which is the pre-FTY-254
    behavior — and total (no dictionary, no I/O).
    """

    variants = {token}
    for suffix, replacement in _SUFFIX_VARIANTS:
        if token.endswith(suffix) and len(token) - len(suffix) >= _MIN_STEM_CHARS:
            variants.add(token[: -len(suffix)] + replacement)
    return frozenset(variants)


def _tokens_match(a: str, b: str) -> bool:
    """Whether two tokens denote the same word under the bounded variant rule."""

    return bool(_variants(a) & _variants(b))


def _contains_token(tokens: tuple[str, ...], wanted: str) -> bool:
    """Whether any of ``tokens`` matches ``wanted`` under the variant rule."""

    return any(_tokens_match(token, wanted) for token in tokens)


def _query_states_form(query_tokens: tuple[str, ...], form_token: str) -> bool:
    """Whether the query states the density-changing form ``form_token``.

    Directly (variant match) or through the form's synonym family in
    :data:`_REJECTED_FORM_FAMILIES` — "banana powder" states ``dehydrated``
    because USDA labels dehydration and powdering as one form, but "banana
    chips" does not.
    """

    if _contains_token(query_tokens, form_token):
        return True
    return any(
        form_token in family and any(token in family for token in query_tokens)
        for family in _REJECTED_FORM_FAMILIES
    )


def is_fdc_description_compatible(query_key: str, description: str) -> bool:
    """Whether one FDC row's ``description`` names the queried food in a usable form.

    Three deterministic gates, all lexical and bounded:

    1. **Head-noun / category gate.** The query's last token is its food
       identity (``hummus`` in ``dill pickle hummus``); a description that never
       names it is a different food — matching only flavor/detail tokens
       (``Pickles, cucumber, dill or kosher dill``) is not a match.
    2. **Density-changing form gate.** Each description token from
       :data:`REJECTED_FORM_TOKENS` the query did not state rejects the row
       (fresh ``banana`` must not cost as banana powder; ``condensed milk``
       must not cost as dry milk). A query states a form directly or through
       its synonym family ("banana powder" covers "dehydrated, or banana
       powder"); stating one form never opts into a different one ("banana
       chips" stays incompatible with the dehydrated/powder row), and the
       ``dry roasted`` preparation idiom states no form at all ("dry roasted
       peanuts" stays incompatible with a dehydrated row).
    3. **Added-ingredient gate.** A query token from
       :data:`ADDED_INGREDIENT_QUERY_TOKENS` missing from the description
       rejects the row (plain toast facts do not cover ``buttered toast``).

    An empty query or empty description cannot be verified either way and stays
    eligible (the facts already passed schema validation and plausibility).
    """

    query_tokens = _tokens(query_key)
    description_tokens = _tokens(description)
    if not query_tokens or not description_tokens:
        return True

    head_noun = query_tokens[-1]
    if not _contains_token(description_tokens, head_noun):
        return False

    form_query_tokens = query_tokens
    if "dry" in query_tokens and frozenset(query_tokens) & _DRY_ROASTED_MARKERS:
        # Query-side "dry roasted ..." is the preparation idiom, not a stated
        # dehydrated/dried/powdered form: drop "dry" so it opts into nothing.
        form_query_tokens = tuple(word for word in query_tokens if word != "dry")

    rejected = REJECTED_FORM_TOKENS
    if frozenset(description_tokens) & _DRY_ROASTED_MARKERS:
        rejected = rejected - {"dry"}
    for token in frozenset(description_tokens):
        if token in rejected and not _query_states_form(form_query_tokens, token):
            return False

    return all(
        _contains_token(description_tokens, token)
        for token in query_tokens
        if token in ADDED_INGREDIENT_QUERY_TOKENS
    )


def fdc_preference_key(query_key: str, description: str) -> tuple[int, int]:
    """Sort key ordering *compatible* rows; lower sorts first (preferred).

    ``(unstated demoted-form count, -query-token coverage)``: prefer the
    common/fresh/simple form (fewest :data:`DEMOTED_FORM_TOKENS` the query did
    not state), then the row naming more of the query's own tokens (a
    ``scrambled`` row beats a plain raw-egg row for ``scrambled eggs``). Callers
    tie-break by the source's original relevance order.
    """

    query_tokens = _tokens(query_key)
    description_tokens = _tokens(description)
    demoted = sum(
        1
        for token in frozenset(description_tokens)
        if token in DEMOTED_FORM_TOKENS and not _contains_token(query_tokens, token)
    )
    coverage = sum(1 for token in query_tokens if _contains_token(description_tokens, token))
    return (demoted, -coverage)

"""Brand-aware packaged-product routing policy (FTY-253).

Deterministic, bounded helpers that let the resolver use a parsed ``brand`` (and
any product tokens the parser stranded in ``quantity_text``) when routing a
packaged product between evidence sources:

- :func:`is_evidence_brand_compatible` — whether one evidence candidate (a USDA
  FDC description, or the product name a fetched page states) is compatible with
  the branded item identity. A generic database hit for the bare food name is a
  *candidate*, not an authority: a row naming a **different** product identity
  (``DENNY'S, chicken strips`` for ``brand=Compliments``) is rejected so the
  branded web/reference/model-prior tiers run instead of committing the wrong
  product or asking the user to restate a count they already gave.
- :func:`product_hint` — the stranded product tokens of a quantity phrase
  (``"4 toppabales brand"`` → ``"toppabales brand"``), extracted through
  :func:`~app.estimator.identity_sanitizer.sanitized_identity` so only bounded
  food-identity tokens — never quantity words, personal context, or prompt
  framing — can reach a search query.
- :func:`identity_variants` — the bounded, ordered set of item-identity queries
  a branded/hinted candidate may search: the normalized ``name + brand`` base,
  the ``name + hint`` and user-stated ``hint + name`` token orders, and a static
  private-label/retailer alias expansion (:data:`RETAILER_BRAND_ALIASES`).

Everything here is item identity only. Every variant is composed from the
parsed ``name`` / ``brand`` / ``quantity_text`` fields, hint tokens pass through
the identity sanitizer, and every query still egresses through the existing
``sanitize_query`` chokepoint in the search adapter — no profile, goals, body
metrics, history, ids, or raw event text can ride along, and the expansion is
deterministic and capped (:data:`MAX_IDENTITY_VARIANTS`), never open-ended
agentic browsing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from app.estimator.detail_signals import _COLLOQUIAL_MEASURE_WORDS, _HOUSEHOLD_UNIT_WORDS
from app.estimator.food_serving import _COUNT_UNITS, _MASS_UNIT_GRAMS, _VOLUME_UNIT_GRAMS
from app.estimator.identity_sanitizer import sanitized_identity
from app.estimator.pipeline import CandidateDraft

#: Hard cap on the identity-query variants one candidate may search per evidence
#: tier. Real expansions are 1-3 queries; the cap is the structural guarantee that
#: query expansion stays bounded (story FTY-253 security scope).
MAX_IDENTITY_VARIANTS: Final[int] = 5

#: Hard cap on the product-hint tokens lifted from a quantity phrase. A real
#: stranded product hint ("toppabales brand", "PC Loblaws store brand") is a few
#: words; a longer run is smuggled context and is truncated.
MAX_HINT_TOKENS: Final[int] = 5

#: Static, bounded private-label/retailer alias expansions, keyed by the
#: normalized brand token string. A store-brand product's nutrition page is often
#: published under the retailer's name (Compliments → Sobeys) or vice versa, so a
#: known alias is appended as one extra identity variant. This is a closed,
#: deterministic map — item identity only, no lookup service — and unknown brands
#: simply get no expansion.
RETAILER_BRAND_ALIASES: Final[Mapping[str, tuple[str, ...]]] = {
    "compliments": ("Sobeys",),
    "sobeys": ("Compliments",),
    "pc": ("Presidents Choice", "Loblaws"),
    "presidents choice": ("PC", "Loblaws"),
    "no name": ("Loblaws",),
    "great value": ("Walmart",),
    "kirkland": ("Costco",),
    "kirkland signature": ("Costco",),
    "selection": ("Metro",),
}

#: Marker words a user attaches to a brand phrase ("compliments **brand**",
#: "PC - Loblaws **store** brand") that name no identity of their own; excluded
#: from brand-token matching so "brand" in an evidence name never fakes a match.
_GENERIC_BRAND_MARKER_TOKENS: Final[frozenset[str]] = frozenset(
    {"brand", "brands", "store", "own", "label", "private"}
)

#: Benign preparation/packaging descriptors a *generic* trusted-database row may
#: carry beyond the food-name tokens ("Chicken strips, breaded, cooked") without
#: naming a different product identity. A bounded documented tunable: a token not
#: on this list and not in the item's own name/brand tokens marks the row as some
#: *other* product (another brand or dish) and rejects it for a branded candidate.
_GENERIC_DESCRIPTION_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "raw",
        "cooked",
        "baked",
        "fried",
        "breaded",
        "battered",
        "grilled",
        "roasted",
        "boiled",
        "steamed",
        "frozen",
        "canned",
        "dried",
        "prepared",
        "unprepared",
        "heated",
        "unheated",
        "plain",
        "salted",
        "unsalted",
        "sweetened",
        "unsweetened",
        "enriched",
        "fortified",
        "homemade",
        "commercial",
        "commercially",
        "ready",
        "eat",
        "serve",
        "all",
        "varieties",
        "nfs",
        "ns",
        "and",
        "or",
        "with",
        "without",
        "the",
        "a",
        "an",
        "of",
        "as",
        "to",
        "style",
        "type",
    }
)

#: Quantity/consumption words dropped from a product hint: unit vocabularies the
#: serving math recognises (mass, volume/household, count/portion nouns), the
#: colloquial measure words, and common consumption verbs/approximators. What
#: survives is the stranded product identity ("toppabales brand"), if any.
_QUANTITY_HINT_TOKENS: Final[frozenset[str]] = frozenset(
    token
    for vocabulary in (
        _MASS_UNIT_GRAMS,
        _VOLUME_UNIT_GRAMS,
        _COUNT_UNITS,
        _HOUSEHOLD_UNIT_WORDS,
        _COLLOQUIAL_MEASURE_WORDS,
    )
    for key in vocabulary
    for token in key.split()
) | frozenset(
    {
        "fl",
        "had",
        "have",
        "having",
        "ate",
        "eat",
        "eaten",
        "eating",
        "drank",
        "drink",
        "drinking",
        "some",
        "few",
        "couple",
        "half",
        "quarter",
        "whole",
    }
)

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
# Straight and curly (U+2019) apostrophes both fuse: "DENNY'S" → "dennys".
_APOSTROPHE_RE: Final[re.Pattern[str]] = re.compile("['\u2019]")
_HAS_ALNUM_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]")
_DIGIT_RE: Final[re.Pattern[str]] = re.compile(r"[0-9]")


def _tokens(text: str) -> tuple[str, ...]:
    """Lower-cased identity tokens with possessive apostrophes fused (DENNY'S → dennys)."""

    return tuple(_TOKEN_RE.findall(_APOSTROPHE_RE.sub("", text.lower())))


def _clean_phrase(text: str) -> str:
    """Collapse whitespace and drop punctuation-only words, keeping token order.

    ``"PC - Loblaws store brand"`` → ``"PC Loblaws store brand"``: search variants
    are composed from real words, so a stray separator never leaks into a query.
    """

    return " ".join(word for word in text.split() if _HAS_ALNUM_RE.search(word))


def _brand_identity_tokens(brand: str) -> frozenset[str]:
    """The tokens that identify ``brand``, including its static retailer aliases."""

    tokens = set(_tokens(brand))
    for alias in brand_alias_expansions(brand):
        tokens.update(_tokens(alias))
    return frozenset(tokens - _GENERIC_BRAND_MARKER_TOKENS)


def brand_alias_expansions(brand: str) -> tuple[str, ...]:
    """Static alias phrases for a known private-label/retailer ``brand``.

    Matched on the normalized full brand first, then on its individual identity
    tokens (so ``"PC - Loblaws store brand"`` still finds the ``pc`` entry). The
    result is deduplicated against the brand's own tokens so an alias the user
    already stated is not re-appended.
    """

    brand_tokens = _tokens(brand)
    identity_tokens = frozenset(brand_tokens) - _GENERIC_BRAND_MARKER_TOKENS
    keyed: list[str] = []
    exact = RETAILER_BRAND_ALIASES.get(" ".join(brand_tokens))
    if exact is not None:
        keyed.extend(exact)
    else:
        for token in brand_tokens:
            keyed.extend(RETAILER_BRAND_ALIASES.get(token, ()))
    expansions: list[str] = []
    for alias in keyed:
        alias_tokens = frozenset(_tokens(alias))
        if alias_tokens and not alias_tokens <= identity_tokens and alias not in expansions:
            expansions.append(alias)
    return tuple(expansions)


def is_evidence_brand_compatible(
    evidence_name: str | None, *, name: str, brand: str | None
) -> bool:
    """Whether one evidence candidate's stated identity fits the branded item.

    Applied to a USDA FDC description or a fetched page's transcribed
    ``product_name`` before that evidence may back a **branded** candidate:

    - a generic candidate (no ``brand``) is never gated here;
    - evidence that states no name cannot be *proven* foreign, so it stays
      eligible (the facts already passed schema validation and plausibility, and
      the query that surfaced them was identity-scoped);
    - evidence naming the brand (or a static retailer alias) is compatible;
    - evidence whose tokens are only the item's own name/brand tokens plus benign
      preparation descriptors (:data:`_GENERIC_DESCRIPTION_TOKENS`) is a plain
      generic row for this food and stays compatible;
    - anything else carries a **different** product identity (another brand or
      dish, e.g. ``DENNY'S, chicken strips``) and is rejected so the resolver
      tries the next evidence candidate or tier.
    """

    if brand is None or not brand.strip():
        return True
    if evidence_name is None or not evidence_name.strip():
        return True
    evidence_tokens = frozenset(_tokens(evidence_name))
    if not evidence_tokens:
        return True
    if evidence_tokens & _brand_identity_tokens(brand):
        return True
    allowed = frozenset(_tokens(name)) | _GENERIC_DESCRIPTION_TOKENS
    return evidence_tokens <= allowed


def product_hint(quantity_text: str) -> str:
    """The stranded product tokens of a quantity phrase, or ``""`` when none.

    The parser sometimes leaves product tokens in ``quantity_text`` instead of
    ``brand`` (``"4 toppabales brand crackers"`` may parse to ``name="crackers"``,
    ``quantity_text="4 toppabales brand"``). The phrase is reduced through
    :func:`sanitized_identity` (framing/personal-context stripped, bounded), then
    number tokens and the quantity/consumption vocabulary are dropped; whatever
    survives is a product-identity hint, capped at :data:`MAX_HINT_TOKENS`.
    """

    identity = sanitized_identity(quantity_text or "")
    kept = [
        token
        for token in identity.split()
        if not _DIGIT_RE.search(token) and token not in _QUANTITY_HINT_TOKENS
    ]
    return " ".join(kept[:MAX_HINT_TOKENS])


def identity_variants(candidate: CandidateDraft) -> tuple[str, ...]:
    """The bounded, ordered item-identity queries for one candidate.

    Order is deterministic: the existing ``name + brand`` base first (so an
    unhinted, unaliased candidate searches exactly what it always did), then the
    quantity-phrase product hint in both token orders — normalized ``name + hint``
    and the user-stated ``hint + name`` — then the static retailer alias
    expansion. Duplicates collapse and the list is capped at
    :data:`MAX_IDENTITY_VARIANTS`. Reference-tier callers append the fixed
    nutrition intent per query; every variant still passes the search adapter's
    ``sanitize_query`` chokepoint before egress.
    """

    name = _clean_phrase(candidate.name)
    brand = _clean_phrase(candidate.brand or "")
    variants: list[str] = []

    def _add(query: str) -> None:
        collapsed = " ".join(query.split())
        if collapsed and collapsed not in variants:
            variants.append(collapsed)

    _add(f"{name} {brand}".strip())
    hint = product_hint(candidate.quantity_text)
    if hint:
        _add(f"{name} {hint}")
        _add(f"{hint} {name}")
    if brand:
        for alias in brand_alias_expansions(brand):
            _add(f"{name} {brand} {alias}")
    return tuple(variants[:MAX_IDENTITY_VARIANTS])

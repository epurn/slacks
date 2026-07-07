"""Comparable-reference aggregation — rough reference evidence (FTY-281).

The evidence tier **between** a single confident source match and the pure model
prior when filling a missing macro on a user-stated calorie item
(``evidence-retrieval.md`` → **Estimating a missing field**, step 2). When the exact
official/reference lookup misses for a recognizable item that carries a usable
detail — the Sobeys "buffalo chicken lime wrap (580 cals)" whose own nutrition page
is not available — the estimator may search **relaxed, brand-dropped** item identity
for several *comparable* public reference items (other buffalo-chicken/lime chicken
wraps), transcribe each page's facts, keep only the **compatible, plausible** ones,
drop **outliers**, and aggregate the survivors into a **rough** per-macro estimate.

This module owns the two **deterministic** halves the story keeps out of the LLM:

- :func:`compatibility` — is a fetched page's item a comparable of the target? It
  checks **food form/category** (a wrap/sandwich is not a salad/bowl) and **major
  ingredient/flavor overlap** (``buffalo``/``chicken``/``lime``) against the target
  identity. The LLM only *transcribes* each page's facts + product name upstream;
  the compatibility judgement here is a pure token comparison over that bounded,
  validated name — never the raw page.
- :func:`aggregate` — over the compatible per-100g compositions, work in **grams per
  kcal** density space (the basis actually committed when scaling to the user's
  stated calorie total), drop compositions that are **outliers** relative to the
  sample median, require at least :data:`MIN_COMPARABLE_SOURCES` survivors, bail when
  the survivors **materially disagree**, and otherwise return the **median** density
  per macro. Median (not a naive mean) so one skewed reference cannot drag the
  result.

The aggregate is explicitly **reference-grade, not an authoritative product fact**:
it ranks below a single-source match and above a pure model prior, names **every**
contributing source ref, and records its compatibility criteria + method as
assumptions (``user_text_step.py`` persists them on the evidence row). Serving-basis
compatibility is guaranteed upstream: only facts that canonicalise to per-100g
(``_to_per_100g`` — per-serving facts with no gram basis are excluded) and clear the
FTY-115/132 plausibility bound reach this module, and the aggregate is only ever used
as a macro **ratio** scaled to the user's stated calories, so mixing serving bases is
impossible by construction.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from typing import Final

from app.estimator.food_serving import NutritionFacts

#: Source-system id recorded on the run ``source_refs`` and named in the evidence
#: assumptions for a comparable-reference aggregate, so a client can tell a rough
#: aggregate from an exact single-source (``reference_source``) match. It is **not** a
#: client ``SourceType`` enum value: a user-stated item stays ``user_text`` and the
#: aggregate only fills its missing macros with ``field_provenance = estimated``; the
#: distinction lives in the assumptions text.
COMPARABLE_REFERENCE_SOURCE = "comparable_reference"

#: Minimum compatible, plausible references that must survive outlier filtering before
#: an aggregate is produced. Below this the field falls through to the model prior
#: rather than averaging too little evidence (``evidence-retrieval.md`` step 2).
MIN_COMPARABLE_SOURCES: Final[int] = 3

#: A contributing composition is an **outlier** when its Atwater macro-fraction vector
#: lies more than this Euclidean distance from the sample median vector, so one bad
#: reference is dropped **before** aggregation. A documented tunable (no labelled
#: comparable-aggregate calibration set exists yet — the same honesty rule the label
#: and macro-cold-pass gates follow).
OUTLIER_DISTANCE: Final[float] = 0.30

#: After outlier removal the survivors must all sit within this Euclidean distance of
#: their own median macro-fraction vector; a wider spread means the sources
#: **materially disagree** and no aggregate is produced (the field falls through to
#: the model prior). Documented tunable, as above.
AGREEMENT_DISTANCE: Final[float] = 0.20

#: The three macros aggregated (calories are the user's stated total, never aggregated).
_MACRO_NAMES: Final[tuple[str, ...]] = ("protein_g", "carbs_g", "fat_g")

#: Atwater energy per gram, used only to normalise a composition into a bounded,
#: comparable macro-**fraction** vector (fraction of energy from each macro) for the
#: outlier/agreement distances — never to compute a stored number.
_KCAL_PER_G: Final[dict[str, float]] = {"protein_g": 4.0, "carbs_g": 4.0, "fat_g": 9.0}

#: Food-form vocabulary, grouped by physical form. Two items are form-**incompatible**
#: only when each names a form and the two forms fall in different groups (a wrap is a
#: sandwich, a salad is a bowl, but a wrap is neither a salad nor a bowl). An item that
#: names no known form is never rejected on form grounds (a bare nutrition table).
_FORM_GROUPS: Final[tuple[frozenset[str], ...]] = (
    frozenset(
        {
            "wrap",
            "wraps",
            "burrito",
            "sandwich",
            "sandwiches",
            "sub",
            "roll",
            "panini",
            "taco",
            "quesadilla",
            "pita",
        }
    ),
    frozenset({"salad", "salads", "bowl", "bowls"}),
    frozenset({"soup", "stew", "chili"}),
    frozenset({"smoothie", "shake", "drink", "juice"}),
    frozenset({"bar", "bars", "cookie", "muffin", "cake", "brownie", "biscuit"}),
    frozenset({"pizza"}),
    frozenset({"burger", "burgers", "cheeseburger", "hamburger"}),
)

#: Non-content words dropped before the ingredient/flavor-overlap check: articles,
#: prepositions, marketing filler, and size words that carry no identity. Every known
#: food-form word is also treated as non-content, so overlap reflects the *ingredients*
#: (``buffalo``/``chicken``/``lime``), not the shared shape (``wrap``).
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "with",
        "and",
        "or",
        "in",
        "on",
        "to",
        "go",
        "for",
        "fresh",
        "style",
        "flavour",
        "flavor",
        "flavoured",
        "flavored",
        "classic",
        "original",
        "new",
        "large",
        "small",
        "medium",
        "regular",
        "mini",
        "jumbo",
        "value",
        "meal",
        "combo",
        "size",
        "pack",
        "each",
        "per",
        "serving",
        "nutrition",
        "facts",
        "calories",
        "kcal",
    }
)

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ComparableCandidate:
    """One compatible public-reference page's canonical per-100g facts + provenance.

    ``facts`` is the schema-validated, plausibility-passed per-100g composition (the
    caller guarantees ``calories > 0``); ``source_ref`` is ``reference_source:<url>``
    (the URL only — never the raw page); ``shared_terms`` / ``form`` record why the
    page was judged a comparable of the target, surfaced in the aggregate assumptions.
    """

    facts: NutritionFacts
    source_ref: str
    shared_terms: tuple[str, ...]
    form: str | None


@dataclass(frozen=True)
class ComparableAggregate:
    """A deterministic median aggregate over compatible references (rough evidence).

    ``densities`` maps each macro name to its aggregated **grams per kcal** (the basis
    scaled to the user's stated calorie total); ``source_refs`` names every surviving
    contributor; ``shared_terms`` / ``forms`` summarise the compatibility criteria and
    ``dropped_outliers`` how many candidates were rejected before aggregation. The
    caller turns ``densities`` into committed macro grams and records the rest as
    assumptions.
    """

    densities: dict[str, float]
    source_refs: tuple[str, ...]
    shared_terms: tuple[str, ...]
    forms: tuple[str, ...]
    dropped_outliers: int


@dataclass(frozen=True)
class _Match:
    """The positive outcome of a compatibility check: why the items are comparable."""

    shared_terms: tuple[str, ...]
    form: str | None


def _tokens(name: str) -> list[str]:
    """Lower-case alphanumeric tokens of an item name (bounded, page-derived data)."""

    return _TOKEN_RE.findall(name.lower())


def _form_group_index(tokens: list[str]) -> int | None:
    """Index of the first food-form group any token belongs to, or ``None``."""

    for token in tokens:
        for index, group in enumerate(_FORM_GROUPS):
            if token in group:
                return index
    return None


def _form_token(tokens: list[str]) -> str | None:
    """The first recognised food-form word among ``tokens``, or ``None``."""

    for token in tokens:
        for group in _FORM_GROUPS:
            if token in group:
                return token
    return None


def _content_terms(tokens: list[str]) -> set[str]:
    """Ingredient/flavor tokens: non-stopword, non-food-form words."""

    forms = frozenset().union(*_FORM_GROUPS)
    return {t for t in tokens if t not in _STOPWORDS and t not in forms}


def compatibility(target_name: str, page_name: str | None) -> _Match | None:
    """Whether ``page_name`` names a comparable of ``target_name``; ``None`` if not.

    Two deterministic checks (``evidence-retrieval.md`` compatibility guardrails):

    - **food form/category** — if both names carry a recognised form and the forms
      belong to different groups (wrap/sandwich vs. salad/bowl), they are
      **incompatible**;
    - **major ingredient/flavor overlap** — the names must share at least one content
      term (``buffalo``/``chicken``/``lime``); a page that overlaps only on the form
      word, or that the transcriber could not even name, is **excluded**.
    """

    if not page_name or not page_name.strip():
        return None
    target_tokens = _tokens(target_name)
    page_tokens = _tokens(page_name)

    target_form = _form_group_index(target_tokens)
    page_form = _form_group_index(page_tokens)
    if target_form is not None and page_form is not None and target_form != page_form:
        return None

    shared = _content_terms(target_tokens) & _content_terms(page_tokens)
    if not shared:
        return None

    return _Match(
        shared_terms=tuple(sorted(shared)),
        form=_form_token(page_tokens) or _form_token(target_tokens),
    )


def _macro_fractions(facts: NutritionFacts) -> tuple[float, ...]:
    """Fraction of energy from each macro — a bounded, comparable composition vector.

    ``calories > 0`` is guaranteed by the caller (a comparable candidate). The vector
    normalises out portion size, so two references with the same composition but
    different densities read as identical.
    """

    return tuple(_KCAL_PER_G[name] * getattr(facts, name) / facts.calories for name in _MACRO_NAMES)


def _distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Euclidean distance between two macro-fraction vectors."""

    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def _median_vector(vectors: list[tuple[float, ...]]) -> tuple[float, ...]:
    """Per-component median of a list of equal-length vectors."""

    return tuple(statistics.median(v[i] for v in vectors) for i in range(len(_MACRO_NAMES)))


def aggregate(candidates: list[ComparableCandidate]) -> ComparableAggregate | None:
    """Median-aggregate compatible references, dropping outliers; ``None`` if too weak.

    Deterministic (the LLM has no part here): normalise each candidate to its Atwater
    macro-fraction vector, drop any lying more than :data:`OUTLIER_DISTANCE` from the
    sample median (one bad reference removed **before** aggregation), require at least
    :data:`MIN_COMPARABLE_SOURCES` survivors, bail when the survivors spread wider than
    :data:`AGREEMENT_DISTANCE` (they **materially disagree**), and otherwise return the
    **median** grams-per-kcal density per macro over the survivors.
    """

    if len(candidates) < MIN_COMPARABLE_SOURCES:
        return None

    fractions = [_macro_fractions(c.facts) for c in candidates]
    median = _median_vector(fractions)
    survivors = [
        candidate
        for candidate, vector in zip(candidates, fractions, strict=True)
        if _distance(vector, median) <= OUTLIER_DISTANCE
    ]
    if len(survivors) < MIN_COMPARABLE_SOURCES:
        return None

    survivor_vectors = [_macro_fractions(c.facts) for c in survivors]
    survivor_median = _median_vector(survivor_vectors)
    if any(_distance(vector, survivor_median) > AGREEMENT_DISTANCE for vector in survivor_vectors):
        # After outlier removal the survivors still disagree materially: don't average
        # noise into a stored number — fall through to the model prior.
        return None

    densities = {
        name: statistics.median(getattr(c.facts, name) / c.facts.calories for c in survivors)
        for name in _MACRO_NAMES
    }
    shared_terms = tuple(sorted({term for c in survivors for term in c.shared_terms}))
    forms = tuple(sorted({c.form for c in survivors if c.form}))
    return ComparableAggregate(
        densities=densities,
        source_refs=tuple(c.source_ref for c in survivors),
        shared_terms=shared_terms,
        forms=forms,
        dropped_outliers=len(candidates) - len(survivors),
    )


def build_missing_macro_fill(
    aggregate_result: ComparableAggregate, calories: float, missing: tuple[str, ...]
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Turn an aggregate into committed missing-macro grams + provenance assumptions.

    Each missing macro is committed at ``density × stated_calories`` (rounded 0.1) — the
    aggregate is used only as a macro **ratio** scaled to the number the user gave, never
    as an absolute product fact. Returns the committed values plus the assumptions that
    record the method, the compatibility summary, and **every** contributing source ref
    (``evidence-retrieval.md`` step 2: never a single anonymous blended number); no raw
    page text is ever included.
    """

    values = {name: round(aggregate_result.densities[name] * calories, 1) for name in missing}

    summary_bits: list[str] = []
    if aggregate_result.forms:
        summary_bits.append("/".join(aggregate_result.forms))
    if aggregate_result.shared_terms:
        summary_bits.append(", ".join(aggregate_result.shared_terms))
    compatibility_summary = "; ".join(summary_bits) if summary_bits else "identity"

    dropped = (
        f", {aggregate_result.dropped_outliers} outlier(s) dropped"
        if aggregate_result.dropped_outliers
        else ""
    )
    method = (
        f"{', '.join(missing)} estimated from a rough comparable-reference aggregate "
        f"(median of {len(aggregate_result.source_refs)} compatible references{dropped}) "
        f"scaled to the stated {calories:g} kcal"
    )
    assumptions = (
        method,
        f"comparable on: {compatibility_summary}",
        *(f"comparable source: {ref}" for ref in aggregate_result.source_refs),
    )
    return values, assumptions

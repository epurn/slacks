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
  identity. The LLM only *cold-pass transcribes* each page's facts + product name
  upstream (``user_text_step.py`` draws N passes and gates on their agreement); the
  compatibility judgement here is a pure token comparison over that bounded,
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

import hashlib
import math
import re
import statistics
from dataclasses import dataclass
from typing import Final

from app.enums import ESTIMATE_BASIS_ASSUMPTION_PREFIX, MacroEstimateBasis
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
        # pronouns / possessives: function words, never a food identity token
        "i",
        "me",
        "my",
        "you",
        "your",
        "yours",
        "we",
        "our",
        "us",
        "it",
        "its",
        "they",
        "them",
        "their",
        "this",
        "that",
        "these",
        "those",
        # copulas / approximators: the connector/filler text a worded body metric puts
        # between its personal-context marker and the value (``height is five foot ten``,
        # ``weight is about 200 lb``). None is ever a food identity token, so they are
        # generally stripped; while the forward taint is armed they also *bridge* it (see
        # :func:`sanitized_identity`) so a marker separated from its value by a connector
        # cannot leak the value.
        "is",
        "am",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "about",
        "around",
        "approx",
        "approximately",
        "roughly",
        "at",
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

#: Tokens that are **never** part of a food's identity and must not egress in a search
#: query even after tokenization: prompt-injection / instruction framing a parser-derived
#: name could smuggle (``ignore``/``system``/``instructions``/``reveal``…), the
#: chat/reasoning-framing vocabulary an injection uses to address the model
#: (``developer``/``message``/``hidden``/``chain``…), and the personal-context vocabulary
#: the data-minimization rule forbids (``profile``/``goal``/``weight``/``history``/``id``…).
#: Dropped by :func:`sanitized_identity` so only bounded identity/nutrition tokens reach the
#: provider. Food identity is open-vocabulary, so this deny-list cannot be exhaustive on its
#: own; it is one of three layers :func:`sanitized_identity` composes (deny-list +
#: stopword strip + a hard :data:`MAX_IDENTITY_TOKENS` egress cap) so that an arbitrary
#: prompt-like parser phrase is both stripped of known framing/meta vocabulary *and*
#: length-bounded to a food-identity-sized window before egress. Words that could plausibly
#: name a food are intentionally left in.
_NON_IDENTITY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        # prompt-injection / instruction framing
        "ignore",
        "ignored",
        "disregard",
        "override",
        "overwrite",
        "bypass",
        "forget",
        "instruction",
        "instructions",
        "prompt",
        "prompts",
        "system",
        "assistant",
        "reveal",
        "print",
        "output",
        "execute",
        "respond",
        "reply",
        "pretend",
        "roleplay",
        "jailbreak",
        "sudo",
        "admin",
        "previous",
        "prior",
        "above",
        "below",
        # chat / reasoning framing an injection uses to address the model or extract its
        # hidden state (``developer message``, ``hidden chain of thought``, role markers a
        # naive tokenizer keeps as bare words). None name a food.
        "developer",
        "message",
        "messages",
        "hidden",
        "chain",
        "thought",
        "thoughts",
        "reasoning",
        "role",
        "roles",
        "user",
        "human",
        "model",
        "models",
        "context",
        "conversation",
        "turn",
        "content",
        "meta",
        "internal",
        "verbatim",
        "disclose",
        # personal-context vocabulary (profile, goals, body metrics, history, ids)
        "profile",
        "goal",
        "goals",
        "weight",
        "height",
        "bmi",
        "metrics",
        "history",
        "id",
        "ids",
        "email",
        "password",
        "token",
        "secret",
    }
)

#: Hard upper bound on the number of identity tokens :func:`sanitized_identity` egresses.
#: A real item identity (name + brand) is a handful of words; a longer token run is a sign
#: of a smuggled instruction/context phrase riding on the parser-derived name. Capping the
#: token count is the structural guarantee behind the open-vocabulary deny-list: even a
#: prompt-like word that is not on the deny-list can only egress inside this bounded,
#: food-identity-sized window, so a bulk instruction/context phrase cannot leave whole.
MAX_IDENTITY_TOKENS: Final[int] = 12

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")

#: A token is *value-shaped* — the shape of an id or body metric (``42``, ``200lb``,
#: ``5ft``) — when it carries a digit. :func:`sanitized_identity` drops value-shaped words
#: that follow a dropped personal-context/framing marker so a marker separated from its
#: value by a space cannot leak the value.
_DIGIT_RE: Final[re.Pattern[str]] = re.compile(r"[0-9]")

#: Bare measurement-unit words a body metric splits across when its value and unit are
#: separated by spaces (``height 5 ft 10 in``, ``weight 200 lb``). These carry a digit on
#: neither their own word nor the deny-list, so without them a unit word would *disarm* the
#: forward taint and let the next value word (``10``) egress. While the taint is armed a
#: pure unit word is dropped and keeps the taint armed, so a whole ``<number> <unit>`` body
#: metric run drops. Only consulted *while tainted* (i.e. immediately after a stripped
#: personal-context marker), so an unqualified unit word elsewhere is unaffected.
_BODY_METRIC_UNITS: Final[frozenset[str]] = frozenset(
    {
        # length
        "ft",
        "feet",
        "foot",
        "in",
        "inch",
        "inches",
        "cm",
        "mm",
        "m",
        "meter",
        "meters",
        "metre",
        "metres",
        "centimeter",
        "centimeters",
        "centimetre",
        "centimetres",
        # mass
        "lb",
        "lbs",
        "pound",
        "pounds",
        "kg",
        "kgs",
        "kilo",
        "kilos",
        "kilogram",
        "kilograms",
        "g",
        "gram",
        "grams",
        "oz",
        "ounce",
        "ounces",
        "stone",
        "stones",
        "st",
    }
)

#: Spelled-out number words a body metric uses when its value is worded rather than a digit
#: (``height five foot ten``, ``weight two hundred pounds``, ``one point eight metres``).
#: These carry no digit, so a digit-only forward taint disarms on them and leaks the metric
#: (``five`` egresses, then ``foot ten`` rides along). Like :data:`_BODY_METRIC_UNITS` they
#: keep the taint armed and drop *only while tainted* (immediately after a stripped
#: personal-context marker), so a whole worded ``<number> <unit> <number>`` body metric run
#: drops — while a worded number elsewhere in an item name (``Seven Up``, ``Half Baked``) is
#: never preceded by a marker and still egresses.
#: Held as a split string (not a one-per-line set literal) so the 31-word vocabulary stays
#: compact — the formatter explodes a set literal one element per line.
_NUMBER_WORDS_TEXT: Final[str] = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty "
    "sixty seventy eighty ninety hundred thousand point"
)
_NUMBER_WORDS: Final[frozenset[str]] = frozenset(_NUMBER_WORDS_TEXT.split())

#: Angle-bracket framing markers (``<end>``, ``<|im_start|>``, ``<system>``…) a prompt
#: injection uses to delimit smuggled instructions. Their **inner** tokens (``end``,
#: ``im``, ``start``…) survive a naive ``[a-z0-9]+`` tokenizer and are not food-identity
#: words, so :func:`sanitized_identity` strips the whole marker — content included —
#: before tokenizing. A trailing unclosed ``<end`` is stripped too (``>`` optional). Real
#: food names never contain angle brackets, so this removes only framing residue.
_STRUCTURAL_FRAMING_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]*>?")


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
class ComparableContributor:
    """The retained provenance for one surviving reference in the aggregate.

    ``source_ref`` is ``reference_source:<url>`` (the URL only — never the raw page);
    ``content_hash`` fingerprints the page's *extracted, canonicalised* per-100g facts
    (:func:`_contributor_content_hash`); ``facts`` is that immutable per-100g snapshot.
    Recording all three per contributor (not just a blended number) is the FTY-281
    evidence-transparency requirement — a client can audit exactly which references,
    with which facts, produced the rough estimate. No raw page text is ever retained.
    """

    source_ref: str
    content_hash: str
    facts: NutritionFacts


@dataclass(frozen=True)
class ComparableAggregate:
    """A deterministic median aggregate over compatible references (rough evidence).

    ``densities`` maps each macro name to its aggregated **grams per kcal** (the basis
    scaled to the user's stated calorie total); ``contributors`` retains every surviving
    reference's ref + content hash + per-100g fact snapshot; ``shared_terms`` / ``forms``
    summarise the compatibility criteria and ``dropped_outliers`` how many candidates
    were rejected before aggregation. The caller turns ``densities`` into committed macro
    grams and records the rest as assumptions.
    """

    densities: dict[str, float]
    contributors: tuple[ComparableContributor, ...]
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


def sanitized_identity(name: str) -> str:
    """Reduce a parser-derived item name to its bounded identity tokens, in order.

    The comparable-reference (and exact) reference search must egress the item's
    *identity only* — the same bounded, lower-cased ``[a-z0-9]+`` token vocabulary the
    deterministic compatibility check reads — never the raw parser phrase. Item identity
    is open-vocabulary, so no single filter is sufficient; three layers compose so that a
    prompt-like parser phrase cannot egress as identity:

    - **Structural framing** a prompt injection would use to smuggle instructions past a
      naive concatenation (quotes, colons, code fences, newlines) carries no identity
      token and is dropped by the tokenizer itself. Angle-bracket framing markers
      (``<end>``, ``<|im_start|>``…) are stripped **with their inner tokens** via
      :data:`_STRUCTURAL_FRAMING_RE` first — the tokenizer alone would keep the bare
      word (``end``) and let framing residue ride along on the query.
    - **Non-identity tokens** that *survive* tokenization but are never part of a food's
      identity are removed: instruction / chat-framing / personal-context words via
      :data:`_NON_IDENTITY_TOKENS` (``ignore``, ``system``, ``developer``, ``message``,
      ``hidden``, ``chain``, ``profile``, ``goal``…) and articles / prepositions /
      marketing filler via :data:`_STOPWORDS` (``the``, ``and``, ``with``…). Prompt-like
      or filler parser output cannot ride along on the query even as bare words. The
      deny-list is applied per **whitespace-delimited word**, not per token: a marker
      taints its whole word, so a personal-context payload value *glued* to a marker by
      punctuation the tokenizer discards (``user_id=42``, ``weight=200lb`` →
      ``['user', 'id', '42']`` / ``['weight', '200lb']``) is dropped *with* the marker
      rather than surviving as an orphaned ``42`` / ``200lb`` token. Fail-closed: a word
      carrying a marker is dropped whole even if it also holds a would-be-identity token,
      because an id or body metric next to a stripped marker must never egress. The taint
      also extends **forward** across whitespace: a marker separated from its value by a
      space (``user id 42``, ``weight 200lb``) would otherwise leave the value word
      (``42`` / ``200lb``) untainted, so a dropped marker word taints the following run of
      *value-shaped* words (any token carrying a digit — the shape of an id or body metric),
      **bare measurement-unit words** (``ft``/``in``/``lb``…, :data:`_BODY_METRIC_UNITS`),
      **spelled-out number words** (``five``/``ten``/``hundred``…, :data:`_NUMBER_WORDS`)
      the value splits across, **and pure connector/filler words** (all tokens are
      stopwords — ``is``/``about``/``of``…, :data:`_STOPWORDS`) a worded metric puts between
      its marker and value (``height 5 ft 10 in``, ``height is five foot ten``, ``weight is
      about 200 lb``). All keep the taint armed, so a whole body metric drops — whether the
      value is a digit or worded and whether or not a connector separates it from the marker
      — rather than a unit, number, or connector word disarming the taint and leaking the
      trailing value. Bridging on a filler word never over-strips food identity because a
      filler word carries no identity token; only a word with a **real** identity token (not
      a stopword/value/unit/number) disarms the taint. This is deliberately narrow: it only
      consumes value/unit/number/filler words *following a marker*, so an open-vocabulary
      numeric food identity that is *not* preceded by a marker (``5 Guys``, ``7 Up``,
      ``Seven Up``) still egresses.
    - **Token-count bound** — because the deny-list cannot be exhaustive over an
      open-vocabulary identity, the surviving identity is truncated to the first
      :data:`MAX_IDENTITY_TOKENS`. A real name + brand fits comfortably; a longer run of
      would-be-identity words is smuggled context and is dropped, so an arbitrary
      instruction/context phrase can only ever egress inside a bounded, food-sized window
      rather than in bulk.

    The caller still passes the result through the ``sanitize_query`` chokepoint
    (control-char strip + length bound) before egress.
    """

    unframed = _STRUCTURAL_FRAMING_RE.sub(" ", name)
    identity: list[str] = []
    tainted = False
    for word in unframed.lower().split():
        word_tokens = _TOKEN_RE.findall(word)
        # A marker anywhere in the word taints the whole word: the marker and any
        # personal-context value glued to it by dropped punctuation drop together. The
        # taint also arms forward so a value the marker introduced across a space drops.
        if any(token in _NON_IDENTITY_TOKENS for token in word_tokens):
            tainted = True
            continue
        # A value-shaped word (any token carrying a digit — the shape of an id or body
        # metric), a bare measurement-unit word, a spelled-out number word, or a pure
        # connector/filler word (all tokens are stopwords — ``is``/``about``/``of``…)
        # drops while the forward taint is armed, and keeps it armed so a run of
        # value/unit/number/filler words (``5 ft 10 in``, ``200 lb``, ``is five foot ten``,
        # ``is about 200 lb``) all drop rather than leaking a unit, a digit value, a worded
        # value, or the value a connector introduces after the marker. A filler word carries
        # no identity, so bridging the taint across it never over-strips a food token; only a
        # word with a real identity token (not a stopword/value/unit/number) disarms the taint.
        if tainted and (
            any(_DIGIT_RE.search(token) for token in word_tokens)
            or (bool(word_tokens) and all(t in _BODY_METRIC_UNITS for t in word_tokens))
            or (bool(word_tokens) and all(t in _NUMBER_WORDS for t in word_tokens))
            or (bool(word_tokens) and all(t in _STOPWORDS for t in word_tokens))
        ):
            continue
        tainted = False
        identity.extend(token for token in word_tokens if token not in _STOPWORDS)
    return " ".join(identity[:MAX_IDENTITY_TOKENS])


def cold_pass_identity(names: list[str | None]) -> str | None:
    """The cold passes' agreed product identity, or ``None`` when they disagree on it.

    A page enters the aggregate only when its cold-pass transcriptions agree on *what the
    product is*, not merely on its macro density: every pass must name the product, no two
    passes may name **conflicting food-form groups** (a wrap vs a salad vs a bowl), and the
    passes must share at least one common **content term** (ingredient/flavor). Returns a
    representative name for the downstream target-compatibility check when they agree, else
    ``None`` — so a page whose transcriptions disagree on the product form can never enter
    the aggregate on the strength of a single compatible pass.
    """

    present = [name for name in names if name and name.strip()]
    if not present or len(present) < len(names):
        return None
    form_indices = {
        index for name in present if (index := _form_group_index(_tokens(name))) is not None
    }
    if len(form_indices) > 1:
        return None
    shared = set.intersection(*(_content_terms(_tokens(name)) for name in present))
    if not shared:
        return None
    return present[0]


def _contributor_content_hash(facts: NutritionFacts) -> str:
    """A reproducible fingerprint of one reference's canonicalised per-100g facts.

    Hashes only the bounded, plausibility-passed per-100g numbers (never the raw page),
    so a contributing reference's snapshot is auditable and de-duplicable without ever
    retaining fetched page content (``evidence-retrieval.md`` → Privacy and Retention).
    """

    canonical = f"per_100g|{facts.calories}|{facts.protein_g}|{facts.carbs_g}|{facts.fat_g}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    contributors = tuple(
        ComparableContributor(
            source_ref=c.source_ref,
            content_hash=_contributor_content_hash(c.facts),
            facts=c.facts,
        )
        for c in survivors
    )
    return ComparableAggregate(
        densities=densities,
        contributors=contributors,
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
    record, in order: a machine-readable **estimate-basis marker** the read-model derives
    ``estimate_basis`` from (``evidence-retrieval.md`` FTY-092 read-model), the method,
    the compatibility summary, and **every** contributing reference with its content hash
    and immutable per-100g fact snapshot (step 2: never a single anonymous blended
    number). No raw page text is ever included.
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
        f"(median of {len(aggregate_result.contributors)} compatible references{dropped}) "
        f"scaled to the stated {calories:g} kcal"
    )
    assumptions = (
        f"{ESTIMATE_BASIS_ASSUMPTION_PREFIX}{MacroEstimateBasis.COMPARABLE_REFERENCE.value}",
        method,
        f"comparable on: {compatibility_summary}",
        *(_contributor_assumption(c) for c in aggregate_result.contributors),
    )
    return values, assumptions


def _contributor_assumption(contributor: ComparableContributor) -> str:
    """One contributing reference's audit line: ref, content hash, per-100g snapshot."""

    facts = contributor.facts
    return (
        f"comparable source: {contributor.source_ref} "
        f"(sha256:{contributor.content_hash}; per_100g "
        f"kcal={facts.calories:g} protein={facts.protein_g:g} "
        f"carbs={facts.carbs_g:g} fat={facts.fat_g:g})"
    )

"""Comparable-reference item identity sanitization.

This module owns the bounded parser-derived identity string that exact and
comparable reference searches may send to provider query sanitization. It keeps
prompt framing, personal context, ids, and body metrics out of reference-search
egress while preserving open-vocabulary food identity tokens.
"""

from __future__ import annotations

import re
from typing import Final

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
#: name could smuggle (``ignore``/``system``/``instructions``/``reveal``...), the
#: chat/reasoning-framing vocabulary an injection uses to address the model
#: (``developer``/``message``/``hidden``/``chain``...), and the personal-context vocabulary
#: the data-minimization rule forbids (``profile``/``goal``/``weight``/``history``/``id``...).
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

#: Angle-bracket framing markers (``<end>``, ``<|im_start|>``, ``<system>``...) a prompt
#: injection uses to delimit smuggled instructions. Their **inner** tokens (``end``,
#: ``im``, ``start``...) survive a naive ``[a-z0-9]+`` tokenizer and are not food-identity
#: words, so :func:`sanitized_identity` strips the whole marker — content included —
#: before tokenizing. A trailing unclosed ``<end`` is stripped too (``>`` optional). Real
#: food names never contain angle brackets, so this removes only framing residue.
_STRUCTURAL_FRAMING_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]*>?")


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
      (``<end>``, ``<|im_start|>``...) are stripped **with their inner tokens** via
      :data:`_STRUCTURAL_FRAMING_RE` first — the tokenizer alone would keep the bare
      word (``end``) and let framing residue ride along on the query.
    - **Non-identity tokens** that *survive* tokenization but are never part of a food's
      identity are removed: instruction / chat-framing / personal-context words via
      :data:`_NON_IDENTITY_TOKENS` (``ignore``, ``system``, ``developer``, ``message``,
      ``hidden``, ``chain``, ``profile``, ``goal``...) and articles / prepositions /
      marketing filler via :data:`_STOPWORDS` (``the``, ``and``, ``with``...). Prompt-like
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
      **bare measurement-unit words** (``ft``/``in``/``lb``..., :data:`_BODY_METRIC_UNITS`),
      **spelled-out number words** (``five``/``ten``/``hundred``..., :data:`_NUMBER_WORDS`)
      the value splits across, **and pure connector/filler words** (all tokens are
      stopwords — ``is``/``about``/``of``..., :data:`_STOPWORDS`) a worded metric puts between
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
        # connector/filler word (all tokens are stopwords — ``is``/``about``/``of``...)
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

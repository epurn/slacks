"""Curated, versioned MET table for the exercise-burn calculator (FTY-043).

The Metabolic Equivalent of Task (MET) is the ratio of an activity's energy cost
to resting energy expenditure: 1 MET is rest, so a 7-MET activity burns energy at
seven times the resting rate. The exercise-burn calculator
(:mod:`app.estimator.exercise`) multiplies a MET value by the user's body weight
and the logged duration to derive active calories.

Trust boundary
--------------

The MET value is **never** supplied by the LLM. The parse step (FTY-042) extracts
only an activity *description* and duration; this module maps that description to a
MET value from a fixed, curated table the backend owns. An activity with no
confident match returns :data:`None` so the calculator can fail closed (route to
``needs_clarification``) rather than guess a burn.

Curation and versioning
------------------------

:data:`MET_TABLE` is a deliberately small **v1 subset** of the 2011 Compendium of
Physical Activities, covering common everyday activities at a single representative
"general / moderate" intensity each. Each entry cites the Compendium activity it is
drawn from. The table is content-addressed by :data:`MET_TABLE_VERSION`; bump the
version whenever a value or alias changes so an estimation run records exactly which
table produced its numbers. Expanding the table beyond this subset, or adding
intensity tiers, is explicitly out of scope (story non-goals).

Reference: Ainsworth BE, et al. "2011 Compendium of Physical Activities: a second
update of codes and MET values." *Med Sci Sports Exerc* 2011;43(8):1575-1581.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

#: Version string for the curated table, recorded on the estimation run as evidence.
#: Bump on any change to a MET value, key, or alias so runs remain reproducible.
MET_TABLE_VERSION: Final[str] = "met/v1"

#: Human-readable source of the MET values, recorded alongside the version.
MET_TABLE_SOURCE: Final[str] = "2011 Compendium of Physical Activities (curated v1 subset)"


@dataclass(frozen=True)
class MetEntry:
    """One curated activity: its canonical key, MET value, and matchable aliases.

    ``met`` is the representative "general / moderate" MET value for the activity
    from the cited Compendium entry. ``aliases`` are the lower-cased phrases that
    map to it (the canonical ``key`` is always matchable too). ``compendium`` notes
    the source activity for auditability.
    """

    key: str
    met: float
    compendium: str
    aliases: frozenset[str] = field(default_factory=frozenset)


#: The curated v1 MET subset. Values are the representative "general / moderate"
#: intensity for each activity from the 2011 Compendium; see the module docstring.
_ENTRIES: Final[tuple[MetEntry, ...]] = (
    MetEntry(
        key="walking",
        met=3.5,
        compendium="walking, 3.0 mph, level, moderate pace",
        aliases=frozenset({"walk", "walking", "brisk walk", "brisk walking"}),
    ),
    MetEntry(
        key="running",
        met=7.0,
        compendium="running, general",
        aliases=frozenset({"run", "running", "jog", "jogging", "going for a run"}),
    ),
    MetEntry(
        key="cycling",
        met=7.5,
        compendium="bicycling, general",
        aliases=frozenset({"cycle", "cycling", "bike", "biking", "bicycling"}),
    ),
    MetEntry(
        key="stationary_cycling",
        met=7.0,
        compendium="bicycling, stationary, general",
        aliases=frozenset({"stationary bike", "exercise bike", "spin", "spinning", "spin class"}),
    ),
    MetEntry(
        key="swimming",
        met=6.0,
        compendium="swimming, general",
        aliases=frozenset({"swim", "swimming", "laps", "swimming laps"}),
    ),
    MetEntry(
        key="rowing",
        met=4.8,
        compendium="rowing, stationary, general, moderate effort",
        aliases=frozenset({"row", "rowing", "rower", "rowing machine"}),
    ),
    MetEntry(
        key="elliptical",
        met=5.0,
        compendium="elliptical trainer, moderate effort",
        aliases=frozenset({"elliptical", "cross trainer", "elliptical trainer"}),
    ),
    MetEntry(
        key="hiking",
        met=6.0,
        compendium="hiking, cross country",
        aliases=frozenset({"hike", "hiking", "trail walk"}),
    ),
    MetEntry(
        key="strength_training",
        met=3.5,
        compendium="resistance (weight) training, multiple exercises, moderate effort",
        aliases=frozenset(
            {
                "weights",
                "weight training",
                "weightlifting",
                "lifting",
                "lifting weights",
                "strength training",
                "resistance training",
            }
        ),
    ),
    MetEntry(
        key="yoga",
        met=2.5,
        compendium="yoga, hatha",
        aliases=frozenset({"yoga", "hatha yoga"}),
    ),
    MetEntry(
        key="pilates",
        met=3.0,
        compendium="pilates, general",
        aliases=frozenset({"pilates"}),
    ),
    MetEntry(
        key="jump_rope",
        met=11.8,
        compendium="rope jumping, moderate pace",
        aliases=frozenset({"jump rope", "jumping rope", "skipping", "skipping rope"}),
    ),
    MetEntry(
        key="basketball",
        met=6.5,
        compendium="basketball, general",
        aliases=frozenset({"basketball", "hoops", "shooting hoops"}),
    ),
    MetEntry(
        key="soccer",
        met=7.0,
        compendium="soccer, casual, general",
        aliases=frozenset({"soccer", "football", "kickabout"}),
    ),
    MetEntry(
        key="tennis",
        met=7.3,
        compendium="tennis, general",
        aliases=frozenset({"tennis"}),
    ),
)


def _build_lookup(entries: tuple[MetEntry, ...]) -> dict[str, MetEntry]:
    """Index every key and alias to its entry, rejecting accidental collisions.

    A duplicate phrase across two entries is a curation bug (two activities would
    silently shadow each other), so it fails loudly at import time rather than
    resolving non-deterministically.
    """

    index: dict[str, MetEntry] = {}
    for entry in entries:
        for phrase in {entry.key, *entry.aliases}:
            normalized = _normalize(phrase)
            if normalized in index and index[normalized] is not entry:
                raise ValueError(f"duplicate MET alias {normalized!r} in curated table")
            index[normalized] = entry
    return index


def _normalize(text: str) -> str:
    """Lower-case, collapse internal whitespace, and strip surrounding punctuation.

    Deterministic and total: matching is exact on the normalized phrase, so the
    same description always maps to the same MET value (or to nothing).
    """

    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    return collapsed.strip(" .,!?;:\"'")


#: All curated MET entries, keyed by canonical key for direct access/iteration.
MET_TABLE: Final[dict[str, MetEntry]] = {entry.key: entry for entry in _ENTRIES}

_LOOKUP: Final[dict[str, MetEntry]] = _build_lookup(_ENTRIES)


def lookup_met(activity: str) -> MetEntry | None:
    """Return the curated MET entry for ``activity``, or ``None`` if no confident match.

    Matching is deterministic and conservative: the normalized description must equal
    a curated key or alias exactly. No fuzzy or partial matching is done — a miss
    returns ``None`` so the caller fails closed rather than guessing a burn from an
    unrecognized activity.
    """

    return _LOOKUP.get(_normalize(activity))

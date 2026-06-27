"""Deterministic text normalization for saved-food matching (FTY-052).

:func:`normalize_text` is the single, named normalization rule the saved-food
typeahead relies on. It is a pure, deterministic function so the normalized form
stored alongside a saved food's name/alias and the normalized form of a search
query are produced identically, on the backend and (mirrored) on the client.

The rule, in order:

1. **Unicode NFKD decomposition** — split accented characters into a base
   character plus its combining marks (and normalize compatibility forms).
2. **Diacritic folding** — drop the combining marks (Unicode category ``Mn``), so
   ``café`` folds to ``cafe``.
3. **Case folding** — :meth:`str.casefold`, a stronger case-insensitive fold than
   :meth:`str.lower` (handles e.g. the German ``ß``).
4. **Whitespace collapsing** — every run of whitespace becomes a single ASCII
   space, with leading/trailing space stripped.

Matching is exact substring (**contains**, which subsumes **prefix**) on the
normalized form. There is deliberately **no** fuzzy, phonetic, stemming, or
semantic step: a query matches only if its normalized text is a literal substring
of the normalized name or alias. This keeps the typeahead deterministic and stable
across clients (see ``docs/contracts/saved-foods.md``).
"""

from __future__ import annotations

import unicodedata


def normalize_text(value: str) -> str:
    """Return the canonical normalized form of ``value`` for saved-food matching.

    Deterministic and idempotent: ``normalize_text(normalize_text(x)) ==
    normalize_text(x)``. The result is case-folded, diacritic-stripped, and
    whitespace-collapsed. A string that contains only whitespace and/or combining
    marks normalizes to the empty string.
    """

    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = without_marks.casefold()
    # ``str.split`` with no argument splits on arbitrary Unicode whitespace runs
    # and drops empty leading/trailing segments, so this both collapses internal
    # whitespace and strips the ends.
    return " ".join(folded.split())

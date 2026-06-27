"""Unit tests for the saved-food normalization/matching rule (FTY-052).

Proves the named contract is deterministic: case folding, diacritic stripping, and
whitespace collapsing produce one stable normalized form, and matching is exact
substring (prefix/contains) on that form with **no** fuzzy or semantic step. The
explicit non-match cases are the security/determinism guarantee that a near-miss
query never returns a result.
"""

from __future__ import annotations

import pytest

from app.normalization import normalize_text


def _matches(query: str, text: str) -> bool:
    """The contract's match predicate: normalized query is a substring of normalized text."""

    return normalize_text(query) in normalize_text(text)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("White Rice", "white rice"),
        ("  Iced   Coffee  ", "iced coffee"),
        ("café", "cafe"),
        ("Crème Brûlée", "creme brulee"),
        ("JALAPEÑO", "jalapeno"),
        ("straße", "strasse"),  # casefold expands ß → ss
        ("\tGreek\nYogurt ", "greek yogurt"),
        ("", ""),
        ("   ", ""),  # whitespace-only normalizes to empty
    ],
)
def test_normalize_text_is_deterministic(value: str, expected: str) -> None:
    assert normalize_text(value) == expected


def test_normalize_text_is_idempotent() -> None:
    once = normalize_text("Café  au LAIT")
    assert normalize_text(once) == once


def test_prefix_and_contains_match() -> None:
    name = "chicken breast"
    # Prefix.
    assert _matches("chick", name)
    # Contains (not a prefix) — proves contains semantics, not prefix-only.
    assert _matches("breast", name)
    # Full string.
    assert _matches("chicken breast", name)


def test_case_diacritic_and_whitespace_folding_match() -> None:
    assert _matches("CAFE", "Café Latte")
    assert _matches("creme", "Crème Brûlée")
    assert _matches("iced coffee", "  Iced   Coffee  ")


@pytest.mark.parametrize(
    ("query", "text"),
    [
        ("chickne", "chicken breast"),  # transposition typo — no fuzzy match
        ("poultry", "chicken breast"),  # synonym — no semantic match
        ("chickenbreast", "chicken breast"),  # missing the separating space
        ("rice white", "white rice"),  # reordered tokens — substring, not bag-of-words
        ("z", "white rice"),  # absent character
    ],
)
def test_near_but_non_matching_strings_are_excluded(query: str, text: str) -> None:
    assert not _matches(query, text)

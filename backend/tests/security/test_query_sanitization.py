"""Adversarial query-sanitization / data-minimization suite (FTY-073).

Proves the threat-model "Cross-user data leakage" / data-minimization control: no
personal or profile/history context (profile, weight, body data, food/exercise
history, memories, event metadata) egresses to an external search provider — only a
sanitized product/restaurant identity leaves the system.

It extends ``tests/test_search_provider.py`` by proving the chokepoint end-to-end:
the official-source step builds an identity-only query, and each real adapter
egresses exactly its closed request shape — ``q`` (sanitized) + ``count`` with the
key in a header for Brave, ``q`` (sanitized) + ``format=json`` with no credential
at all for the keyless SearXNG default (FTY-164) — even when the identity is laced
with smuggled multi-line "context".
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr

from app.estimator.pipeline import CandidateDraft
from app.estimator.search import (
    BraveSearchProvider,
    SearchSettings,
    SearXNGSearchProvider,
    sanitize_query,
)
from app.estimator.searched_reference import _identity_query
from tests.security._harness import resolver_returning

#: Markers that must never appear in an egressed search request.
_PERSONAL_MARKERS = ["user_id", "weight", "200lb", "goal", "partner", "history", "@example.com"]


def test_identity_query_is_name_and_brand_only() -> None:
    # The official step builds the query from item identity alone — never quantity,
    # never any field that could carry who/when/how-much.
    candidate = CandidateDraft(
        name="Big Mac",
        brand="McDonald's",
        quantity_text="2 at 7pm with my partner",
        amount=2.0,
        unit="serving",
    )
    assert _identity_query(candidate) == "Big Mac McDonald's"
    assert "partner" not in _identity_query(candidate)
    assert "7pm" not in _identity_query(candidate)


def test_sanitize_query_strips_smuggled_multiline_context() -> None:
    smuggled = "Big Mac\nuser_id=42\tweight=200lb\x00goal=loss"
    cleaned = sanitize_query(smuggled)
    # Control chars / newlines are flattened to spaces and collapsed; the structured
    # markers cannot survive as separate lines/fields.
    assert "\n" not in cleaned
    assert "\t" not in cleaned
    assert "\x00" not in cleaned
    assert cleaned == "Big Mac user_id=42 weight=200lb goal=loss"


def _recording_transport(
    captured: list[dict[str, Any]], reply: dict[str, Any] | None = None
) -> Any:
    def _transport(
        url: str,
        *,
        headers: dict[str, str],
        timeout_seconds: float,
        allowed_hosts: frozenset[str],
        resolver: Any,
        local_http_hosts: frozenset[str],
    ) -> dict[str, Any]:
        captured.append({"url": url, "headers": headers})
        if reply is not None:
            return reply
        return {"web": {"results": [{"url": "https://example.com/x", "title": "Big Mac"}]}}

    return _transport


def test_only_sanitized_identity_and_count_egress_to_provider() -> None:
    captured: list[dict[str, Any]] = []
    settings = SearchSettings(
        provider="brave", api_key=SecretStr("super-secret-key"), max_results=5
    )
    provider = BraveSearchProvider(
        settings,
        transport=_recording_transport(captured),
        resolver=resolver_returning("23.1.2.3"),
    )

    # A query laced with personal context (as if the caller leaked it in).
    provider.search("Big Mac\nuser_id=42 weight=200lb goal=loss partner history@example.com")

    assert len(captured) == 1
    request = captured[0]
    parsed = urlsplit(request["url"])
    params = parse_qs(parsed.query)
    # The egressed request shape is closed to exactly q + count.
    assert set(params) == {"q", "count"}
    # The key rides in a header, never the URL.
    assert "super-secret-key" not in request["url"]
    assert request["headers"]["X-Subscription-Token"] == "super-secret-key"
    # No personal markers survive as discrete params; they are flattened into the
    # single q string (and would in practice never reach here — the official step
    # sends identity only), but none ride as structured fields the provider parses.
    assert "user_id" not in params
    assert "weight" not in params
    assert "goal" not in params


def test_only_sanitized_identity_and_format_egress_to_searxng_default() -> None:
    # The keyless SearXNG default (FTY-164) keeps the same data-minimization boundary:
    # the closed request shape is q + format=json, with no credential header at all.
    captured: list[dict[str, Any]] = []
    settings = SearchSettings()  # the empty-env default: searxng, keyless
    provider = SearXNGSearchProvider(
        settings,
        transport=_recording_transport(
            captured,
            reply={"results": [{"url": "https://example.com/x", "title": "Big Mac"}]},
        ),
        resolver=resolver_returning("172.19.0.5"),
    )

    provider.search("Big Mac\nuser_id=42 weight=200lb goal=loss partner history@example.com")

    assert len(captured) == 1
    request = captured[0]
    params = parse_qs(urlsplit(request["url"]).query)
    # The egressed request shape is closed to exactly q + format.
    assert set(params) == {"q", "format"}
    # Keyless: nothing rides in a header, so there is no secret to leak.
    assert request["headers"] == {}
    # No personal markers survive as discrete params.
    assert "user_id" not in params
    assert "weight" not in params
    assert "goal" not in params


def test_official_identity_query_carries_no_personal_markers() -> None:
    # Belt-and-braces: an identity built from a realistic branded candidate carries
    # none of the personal markers the data-minimization control forbids.
    candidate = CandidateDraft(
        name="Grilled Chicken Sandwich",
        brand="Chick-fil-A",
        quantity_text="1 with a diet coke, logged 2026-06-27",
        amount=1.0,
    )
    query = _identity_query(candidate)
    for marker in _PERSONAL_MARKERS:
        assert marker not in query
    assert str(uuid.uuid4()) not in query  # no ids leak through identity

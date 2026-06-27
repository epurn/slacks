"""Tests for the pluggable official-source search-provider adapter (FTY-079).

Exercise the full Brave adapter with a stubbed (network-free) transport: the
adapter sends only the sanitized item-identity query (no personal context, the key
in a header), maps the provider reply to candidate URLs + an explicit status,
reports disabled/unavailable without a key, and classifies failures by status
(rate-limited vs. failed) without leaking content. Also pin the config contract:
an unknown provider or a non-https base URL fails closed, and the key is env-only,
masked, and never client-exposed.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr, ValidationError

from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
)
from app.estimator.search import (
    OFFICIAL_SOURCE,
    BraveSearchProvider,
    SearchSettings,
    SearchStatus,
    build_search_provider,
    load_search_settings,
    sanitize_query,
)

# A non-secret test key. The adapter must keep it out of the URL and out of logs.
_TEST_KEY = "test-brave-subscription-key"

# A minimal Brave web-search reply with two usable candidate URLs.
_BRAVE_RESPONSE: dict[str, Any] = {
    "web": {
        "results": [
            {"url": "https://example-restaurant.com/menu", "title": "Menu — Example"},
            {"url": "https://manufacturer.example.com/product", "title": "Product facts"},
        ]
    }
}


class _RecordingTransport:
    """A fake transport that records its call and returns a canned reply (or raises)."""

    def __init__(self, reply: dict[str, Any] | Exception) -> None:
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def _provider(
    reply: dict[str, Any] | Exception,
    **overrides: Any,
) -> tuple[BraveSearchProvider, _RecordingTransport]:
    settings = SearchSettings(api_key=SecretStr(_TEST_KEY), **overrides)
    transport = _RecordingTransport(reply)
    return BraveSearchProvider(settings, transport=transport), transport


# --- Happy path: candidate URLs + status -------------------------------------


def test_search_returns_candidate_urls_with_success_status() -> None:
    provider, _ = _provider(_BRAVE_RESPONSE)

    result = provider.search("grilled chicken sandwich brand")

    assert result.status is SearchStatus.SUCCESS
    assert [c.url for c in result.candidates] == [
        "https://example-restaurant.com/menu",
        "https://manufacturer.example.com/product",
    ]
    assert result.candidates[0].title == "Menu — Example"


def test_search_drops_non_http_urls_and_bounds_to_max_results() -> None:
    reply = {
        "web": {
            "results": [
                {"url": "ftp://internal/secret", "title": "blocked scheme"},
                {"url": "https://a.example.com", "title": "a"},
                {"url": "https://b.example.com", "title": "b"},
                {"url": "https://c.example.com", "title": "c"},
            ]
        }
    }
    provider, _ = _provider(reply, max_results=2)

    result = provider.search("pizza")

    # The ftp URL is dropped; the https list is capped at max_results.
    assert result.status is SearchStatus.SUCCESS
    assert [c.url for c in result.candidates] == ["https://a.example.com", "https://b.example.com"]


def test_search_answer_without_usable_candidate_is_partial() -> None:
    provider, _ = _provider({"web": {"results": []}})

    result = provider.search("obscure item")

    assert result.status is SearchStatus.PARTIAL
    assert result.candidates == ()


def test_search_missing_web_block_is_partial() -> None:
    provider, _ = _provider({})

    assert provider.search("item").status is SearchStatus.PARTIAL


# --- Disabled / unavailable (disabled-by-default posture) ---------------------


def test_unavailable_without_key_makes_no_call() -> None:
    settings = SearchSettings()  # no api_key bundled
    transport = _RecordingTransport(_BRAVE_RESPONSE)
    provider = BraveSearchProvider(settings, transport=transport)

    result = provider.search("item")

    assert result.status is SearchStatus.UNAVAILABLE
    assert result.candidates == ()
    assert transport.calls == []
    assert provider.available is False


def test_disabled_flag_reports_disabled_and_makes_no_call() -> None:
    provider, transport = _provider(_BRAVE_RESPONSE, enabled=False)

    result = provider.search("item")

    assert result.status is SearchStatus.DISABLED
    assert transport.calls == []
    assert provider.enabled is False


def test_empty_query_is_partial_without_calling() -> None:
    provider, transport = _provider(_BRAVE_RESPONSE)

    result = provider.search("   \n\t  ")

    assert result.status is SearchStatus.PARTIAL
    assert transport.calls == []


# --- Query sanitization / data minimization -----------------------------------


def test_search_sends_only_sanitized_query_and_no_personal_context() -> None:
    provider, transport = _provider(_BRAVE_RESPONSE)

    # A query that *attempts* to smuggle multi-line / structured personal context.
    provider.search("burrito\nweight=200lb\nuser_id=42\tgoal=loss")

    call = transport.calls[0]
    parts = urlsplit(call["url"])
    params = parse_qs(parts.query)

    # The request shape is closed: only the sanitized query and the result count.
    assert set(params) == {"q", "count"}
    # Control characters are collapsed to spaces by the single sanitizer chokepoint;
    # there is no separate field through which profile/weight/history could egress.
    assert params["q"] == ["burrito weight=200lb user_id=42 goal=loss"]
    # None of the structured personal fields survive as their own request parameters.
    assert "weight" not in params
    assert "user_id" not in params
    assert "goal" not in params


def test_sanitize_query_strips_control_chars_collapses_and_bounds_length() -> None:
    assert sanitize_query("  hello\n\tworld  ") == "hello world"
    assert sanitize_query("a\x00b\x1fc\x7fd") == "a b c d"
    long = "x" * 500
    assert len(sanitize_query(long)) == 256


def test_only_item_identity_can_reach_the_provider_by_signature() -> None:
    # The adapter accepts a single string; there is no parameter for a profile,
    # weight, history, or event metadata — data minimization is structural.
    provider, transport = _provider(_BRAVE_RESPONSE)

    provider.search("kale salad")

    call = transport.calls[0]
    assert parse_qs(urlsplit(call["url"]).query)["q"] == ["kale salad"]


# --- Secret / key handling ----------------------------------------------------


def test_key_travels_in_header_never_in_the_url() -> None:
    provider, transport = _provider(_BRAVE_RESPONSE)

    provider.search("tacos")

    call = transport.calls[0]
    assert call["headers"]["X-Subscription-Token"] == _TEST_KEY
    # The key never appears in the (loggable) URL query string.
    assert _TEST_KEY not in call["url"]
    assert "X-Subscription-Token" not in call["url"]


def test_key_is_read_from_env_only() -> None:
    settings = load_search_settings({"FATTY_SEARCH_API_KEY": _TEST_KEY})

    assert settings.is_available is True
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == _TEST_KEY


def test_key_is_masked_in_repr_and_str() -> None:
    settings = SearchSettings(api_key=SecretStr(_TEST_KEY))

    # Pydantic SecretStr keeps the raw value out of repr/str so it cannot be logged.
    assert _TEST_KEY not in repr(settings)
    assert _TEST_KEY not in str(settings.api_key)


def test_capability_descriptor_carries_no_secret() -> None:
    provider, _ = _provider(_BRAVE_RESPONSE)

    capability = provider.capability

    assert capability.id == OFFICIAL_SOURCE
    assert capability.enabled is True
    assert capability.available is True
    # No field on the descriptor can carry the key.
    assert _TEST_KEY not in repr(capability)


# --- Status mapping for transport failures (content-free) ---------------------


def test_rate_limit_response_maps_to_rate_limited_status() -> None:
    provider, _ = _provider(FetchResponseError("provider returned HTTP 429", status_code=429))

    result = provider.search("item")

    assert result.status is SearchStatus.RATE_LIMITED
    assert result.candidates == ()


def test_other_4xx_response_maps_to_failed() -> None:
    provider, _ = _provider(FetchResponseError("provider returned HTTP 403", status_code=403))

    assert provider.search("item").status is SearchStatus.FAILED


def test_transient_error_maps_to_failed() -> None:
    provider, _ = _provider(FetchTransientError("provider request failed"))

    assert provider.search("item").status is SearchStatus.FAILED


def test_policy_error_maps_to_failed() -> None:
    provider, _ = _provider(FetchPolicyError("host_not_allowed"))

    assert provider.search("item").status is SearchStatus.FAILED


def test_failure_statuses_do_not_leak_query_or_key() -> None:
    # A failed lookup surfaces a status, never an exception echoing the query/key.
    provider, _ = _provider(FetchResponseError("provider returned HTTP 500", status_code=500))

    result = provider.search("secret restaurant name")

    assert result.status is SearchStatus.FAILED
    assert result.candidates == ()


# --- Non-conforming provider body (untrusted input → status, not exception) ---


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param({"web": {"results": [{"url": 12345, "title": "n"}]}}, id="non_string_url"),
        pytest.param({"web": {"results": "not-a-list"}}, id="non_list_results"),
        pytest.param({"web": "not-a-dict"}, id="non_dict_web"),
        pytest.param(
            {"web": {"results": [{"url": "https://a.example.com", "title": 99}]}},
            id="non_string_title",
        ),
    ],
)
def test_malformed_response_body_maps_to_failed(malformed: dict[str, Any]) -> None:
    # The body is untrusted (the base URL is self-host-overridable). A non-conforming
    # reply must resolve to a status, never escape as an uncaught ValidationError whose
    # repr would echo the provider input.
    provider, _ = _provider(malformed)

    result = provider.search("item")

    assert result.status is SearchStatus.FAILED
    assert result.candidates == ()


def test_malformed_response_does_not_leak_provider_input() -> None:
    input_marker = "leaked-provider-input-marker"
    provider, _ = _provider({"web": {"results": [{"url": object(), "title": input_marker}]}})

    result = provider.search("item")

    # The status is content-free; the untrusted body never surfaces.
    assert result.status is SearchStatus.FAILED
    assert input_marker not in repr(result)


def test_overlong_title_is_truncated_not_rejected() -> None:
    # One overlong title must not fail the whole (otherwise usable) reply — it is a
    # guard on untrusted content, so it truncates rather than mapping to FAILED.
    reply = {"web": {"results": [{"url": "https://a.example.com", "title": "T" * 5000}]}}
    provider, _ = _provider(reply)

    result = provider.search("item")

    assert result.status is SearchStatus.SUCCESS
    assert len(result.candidates) == 1
    assert len(result.candidates[0].title) == 300
    assert result.candidates[0].url == "https://a.example.com"


# --- Config contract ----------------------------------------------------------


def test_status_values_align_with_evidence_retrieval_vocabulary() -> None:
    # The FTY-045 evidence-retrieval status vocabulary, exactly.
    assert {s.value for s in SearchStatus} == {
        "disabled",
        "unavailable",
        "rate_limited",
        "failed",
        "partial",
        "success",
    }


def test_settings_reject_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        SearchSettings(provider="duckduckgo")


def test_settings_require_https_base_url() -> None:
    with pytest.raises(ValidationError):
        SearchSettings(base_url="http://insecure.example.com")


def test_settings_default_to_brave_disabled_by_default_without_key() -> None:
    settings = SearchSettings()

    assert settings.provider == "brave"
    assert settings.enabled is True  # selected/on...
    assert settings.is_available is False  # ...but no bundled key → unavailable


def test_query_url_carries_only_q_and_count() -> None:
    settings = SearchSettings(api_key=SecretStr(_TEST_KEY), max_results=3)

    url = settings.query_url("sushi")
    params = parse_qs(urlsplit(url).query)

    assert settings.allowed_hosts == frozenset({"api.search.brave.com"})
    assert url.startswith("https://api.search.brave.com/res/v1/web/search?")
    assert params == {"q": ["sushi"], "count": ["3"]}


def test_load_search_settings_reads_env_prefix() -> None:
    settings = load_search_settings(
        {"FATTY_SEARCH_ENABLED": "false", "FATTY_SEARCH_MAX_RESULTS": "7"}
    )

    assert settings.enabled is False
    assert settings.max_results == 7


def test_build_search_provider_returns_brave_adapter() -> None:
    provider = build_search_provider(SearchSettings(api_key=SecretStr(_TEST_KEY)))

    assert isinstance(provider, BraveSearchProvider)

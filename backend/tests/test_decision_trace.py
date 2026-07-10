"""Unit tests for the sanitized estimator decision trace (FTY-255).

Prove the trace-entry construction layer with adversarial raw input: control
characters, URLs carrying credential-style query parameters, and secret-looking
strings must never survive into a trace entry, entry fields are a closed set,
counts are clamped, and the per-run entry bound truncates with a single marker.
"""

from __future__ import annotations

import uuid

import pytest

from app.estimator.decision_trace import (
    MAX_TRACE_DESC_LEN,
    MAX_TRACE_ENTRIES,
    MAX_TRACE_LABEL_LEN,
    MAX_TRACE_REF_LEN,
    amount_kind,
    build_decision_entry,
    sanitize_trace_label,
    sanitize_trace_source_ref,
)
from app.estimator.pipeline import EstimationContext


def _context() -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text="two eggs")


class TestAmountKind:
    def test_mass_units(self) -> None:
        assert amount_kind("g", 150.0, "150g") == "mass"
        assert amount_kind("oz", 2.0, "2 oz") == "mass"

    def test_volume_units(self) -> None:
        assert amount_kind("ml", 250.0, "250 ml") == "volume"
        assert amount_kind("cup", 1.0, "1 cup") == "volume"
        assert amount_kind("tbsp", 2.0, "2 tbsp") == "volume"

    def test_counts(self) -> None:
        assert amount_kind(None, 3.0, "3") == "count"
        assert amount_kind("slices", 2.0, "2 slices") == "count"
        assert amount_kind("servings", 1.0, "1 serving") == "count"

    def test_missing_and_unknown(self) -> None:
        assert amount_kind(None, None, "") == "missing"
        assert amount_kind(None, None, "a splash") == "unknown"
        assert amount_kind("parsecs", 1.0, "1 parsec") == "unknown"


class TestLabelSanitization:
    def test_control_characters_are_stripped(self) -> None:
        assert sanitize_trace_label("a\x00b\x1fc\x7fd\ne") == "a b c d e"

    def test_key_value_secrets_are_redacted(self) -> None:
        for raw in (
            "api_key=sk_live_123456",
            "token: abc.def.ghi",
            "password=hunter2",
            "Authorization: Basic dXNlcg",
        ):
            sanitized = sanitize_trace_label(raw)
            assert "[redacted]" in sanitized
            assert "hunter2" not in sanitized
            assert "sk_live_123456" not in sanitized

    def test_bearer_and_provider_keys_are_redacted(self) -> None:
        assert "abcdef" not in sanitize_trace_label("Bearer abcdefghijklmnop")
        assert "sk-proj" not in sanitize_trace_label("sk-proj-abcdefgh1234")

    def test_long_opaque_blobs_are_redacted(self) -> None:
        blob = "A" * 48
        assert blob not in sanitize_trace_label(f"prefix {blob} suffix")

    def test_length_is_bounded(self) -> None:
        assert len(sanitize_trace_label("word " * 100)) <= MAX_TRACE_LABEL_LEN


class TestSourceRefSanitization:
    def test_plain_source_ids_pass_through(self) -> None:
        assert sanitize_trace_source_ref("usda_fdc:12345") == "usda_fdc:12345"
        assert sanitize_trace_source_ref("model_prior") == "model_prior"

    def test_url_query_and_fragment_are_dropped(self) -> None:
        ref = sanitize_trace_source_ref(
            "official_source:https://shop.example.com/p/hummus?api_key=SECRETTOKEN99&s=1#frag"
        )
        assert ref == "official_source:https://shop.example.com/p/hummus"
        assert "SECRETTOKEN99" not in ref

    def test_userinfo_is_dropped(self) -> None:
        ref = sanitize_trace_source_ref("reference_source:https://user:pw@host.example/a/b")
        assert ref == "reference_source:https://host.example/a/b"
        assert "pw" not in ref

    def test_bare_url_keeps_scheme_host_path(self) -> None:
        assert (
            sanitize_trace_source_ref("https://host.example:8443/a?x=1")
            == "https://host.example:8443/a"
        )

    def test_control_characters_and_length_are_bounded(self) -> None:
        ref = sanitize_trace_source_ref(
            "official_source:https://host.example/" + "\x00seg\x1f/" + "p" * 500
        )
        assert "\x00" not in ref
        assert len(ref) <= MAX_TRACE_REF_LEN

    def test_secret_looking_plain_ref_is_redacted(self) -> None:
        assert "SECRET" not in sanitize_trace_source_ref("token=SECRET")


class TestBuildDecisionEntry:
    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown decision-trace fields"):
            build_decision_entry("food_resolve", "source", raw_text="two eggs")

    def test_none_values_are_omitted(self) -> None:
        entry = build_decision_entry(
            "food_resolve", "source", candidate_index=None, tier="usda_fdc", outcome="miss"
        )
        assert entry == {
            "step": "food_resolve",
            "decision": "source",
            "tier": "usda_fdc",
            "outcome": "miss",
        }

    def test_counts_are_clamped(self) -> None:
        entry = build_decision_entry(
            "official_source_resolve",
            "search",
            candidate_index=-3,
            result_count=10_000_000,
        )
        assert entry["candidate_index"] == 0
        assert entry["result_count"] == 9_999

    def test_bool_and_desc_fields(self) -> None:
        entry = build_decision_entry(
            "food_resolve",
            "candidate",
            has_brand=1,
            source_desc="PICKLES, cucumber " + "x" * 200,
        )
        assert entry["has_brand"] is True
        assert len(entry["source_desc"]) <= MAX_TRACE_DESC_LEN


class TestRecordDecisionBound:
    def test_truncates_with_a_single_marker(self) -> None:
        context = _context()
        for index in range(MAX_TRACE_ENTRIES + 25):
            context.record_decision("food_resolve", "source", candidate_index=index, outcome="miss")
        assert len(context.trace) == MAX_TRACE_ENTRIES + 1
        assert context.trace[-1]["decision"] == "trace_truncated"
        markers = [e for e in context.trace if e.get("decision") == "trace_truncated"]
        assert len(markers) == 1

    def test_adversarial_fields_never_reach_the_trace_raw(self) -> None:
        context = _context()
        context.record_decision(
            "official_source_resolve",
            "fetch",
            source_ref="official_source:https://evil.example/p?token=TOPSECRET42#x",
            outcome="fetch_403\x00Bearer LEAKYTOKENVALUE",
        )
        serialized = str(context.trace)
        assert "TOPSECRET42" not in serialized
        assert "LEAKYTOKENVALUE" not in serialized
        assert "\x00" not in serialized

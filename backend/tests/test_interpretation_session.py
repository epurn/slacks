"""Unit and integration tests for the interpretation session (FTY-325).

Network-free, scripted-provider tests for
:class:`app.estimator.interpretation.InterpretationSession`: the session owns
the run's raw text and revisable item hypothesis, structural sample
disagreement (item count/identity/brand) triggers a bounded re-interpretation
instead of a majority-vote collapse, revisions are traced under sanitized
labels only, and the audited two-item-branded collapse case no longer freezes
a degenerate single generic candidate.

The FakeProvider scripts one reply per provider call: N self-consistency
samples (2 when the first window is unanimous, 3 when contested) plus — when
the samples structurally disagree — one re-interpretation reply.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.estimator.interpretation import (
    EvidenceRecord,
    InterpretationSession,
    hypothesis_samples_disagree,
)
from app.estimator.parse import ParseStep
from app.estimator.parse_policy import ParsePolicySettings
from app.estimator.pipeline import (
    EstimationContext,
    NeedsClarification,
    PipelineOutcome,
    StepError,
    StepFailed,
    default_pipeline,
)
from app.estimator.self_consistency import SELF_CONSISTENCY_NUM_SAMPLES
from app.llm.errors import LLMError, LLMTransientError
from app.llm.providers.fake import FakeProvider
from app.schemas.parse import ParseResult

#: A sentinel embedded in raw diary text, asserted absent from every sanitized
#: run surface (trace/assumptions/source_refs/validation_errors).
_RAW_SENTINEL = "RAW-DIARY-SENTINEL"


def _context(raw_text: str) -> EstimationContext:
    return EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text=raw_text)


def _parsed(items: list[dict[str, object]], confidence: float = 0.9) -> dict[str, Any]:
    return {"disposition": "parsed", "confidence": confidence, "items": items}


def _result(items: list[dict[str, object]], confidence: float = 0.9) -> ParseResult:
    return ParseResult.model_validate(_parsed(items, confidence))


def _revision_entries(context: EstimationContext) -> list[dict[str, Any]]:
    return [entry for entry in context.trace if entry.get("decision") == "hypothesis_revision"]


def _outcomes(context: EstimationContext) -> list[str]:
    return [entry["outcome"] for entry in _revision_entries(context)]


# --- the audited collapse case (story acceptance) ----------------------------------

#: The correct two-item branded interpretation of the audited phrase shape:
#: both items carry a brand and an amount.
_TWO_ITEM_REPLY = _parsed(
    [
        {
            "type": "food",
            "name": "chicken strips",
            "quantity_text": "4 strips",
            "amount": 4,
            "brand": "Compliments",
        },
        {
            "type": "food",
            "name": "dill pickle hummus",
            "quantity_text": "2 tbsp",
            "amount": 2,
            "unit": "tbsp",
            "brand": "PC",
        },
    ],
    confidence=0.85,
)


#: The degenerate collapse: one generic, brandless, amountless candidate mashing
#: both items together — and *more self-confident* than the correct sample, so
#: the retired majority-vote aggregation would have frozen it.
def _degenerate(confidence: float) -> dict[str, Any]:
    return _parsed(
        [{"type": "food", "name": "chicken strips with hummus", "quantity_text": ""}],
        confidence=confidence,
    )


def _collapse_provider(reinterpretation_reply: dict[str, Any] | LLMError) -> FakeProvider:
    """Three structurally-disagreeing samples, then the scripted re-ask reply."""

    return FakeProvider(
        responses=[_degenerate(0.95), _TWO_ITEM_REPLY, _degenerate(0.9), reinterpretation_reply],
        max_retries=0,
    )


def test_collapse_case_reinterprets_instead_of_freezing_degenerate_candidate() -> None:
    # The live failure class (story Outcome): mixed-quality samples must not
    # aggregate into a frozen single generic candidate. Disagreement on item
    # count/identity/brand fires one re-interpretation call, and the surviving
    # hypothesis carries both items with brands and amounts.
    provider = _collapse_provider(_TWO_ITEM_REPLY)
    context = _context(f"compliments chicken strips and PC dill pickle hummus {_RAW_SENTINEL}")

    ParseStep(provider).run(context)

    # The contested window paid the full N samples plus exactly one re-ask.
    assert len(provider.prompts) == SELF_CONSISTENCY_NUM_SAMPLES + 1
    assert "disagreed" in provider.prompts[-1]
    assert "<log_entry>" in provider.prompts[-1]

    assert [c.name for c in context.food_candidates] == ["chicken strips", "dill pickle hummus"]
    assert [c.brand for c in context.food_candidates] == ["Compliments", "PC"]
    assert [c.amount for c in context.food_candidates] == [4, 2]
    assert context.clarification_questions == []

    # The revision is recorded under sanitized labels: the collapsed candidate
    # split into two added branded items.
    outcomes = _outcomes(context)
    assert "initial_hypothesis" in outcomes
    assert outcomes.count("item_split") == 1
    assert outcomes.count("item_added") == 2
    added = [e for e in _revision_entries(context) if e["outcome"] == "item_added"]
    assert all(entry["has_brand"] is True for entry in added)
    assert [entry["amount_kind"] for entry in added] == ["count", "volume"]

    # The session survives on the context with the revised hypothesis and lineage.
    session = context.interpretation_session
    assert session is not None
    assert session.hypothesis is not None
    assert session.hypothesis.revision == 1
    assert [item.candidate.name for item in session.hypothesis.items] == [
        "chicken strips",
        "dill pickle hummus",
    ]
    assert len(session.hypothesis.item_links) == 2  # split lineage: 1 source → 2 items


def test_reask_prompt_carries_current_hypothesis_view() -> None:
    # The FTY-324 decision-point shape: a model-consultable re-ask passes the
    # raw text, clarification answers, *current hypothesis*, and evidence view
    # back to the model — the re-ask must see the item set and fields it is
    # revising, not just the inputs that produced them.
    provider = _collapse_provider(_TWO_ITEM_REPLY)
    context = _context("compliments chicken strips and PC dill pickle hummus")

    ParseStep(provider).run(context)

    reask_prompt = provider.prompts[-1]
    assert "<current_hypothesis>" in reask_prompt
    # The representative (most self-confident) degenerate sample is the current
    # hypothesis at re-ask time; its exact item line is shown to the model.
    assert '1. food "chicken strips with hummus"' in reask_prompt
    # The initial samples carry no hypothesis block — there is nothing to
    # revise yet on a first reading.
    assert all("<current_hypothesis>" not in prompt for prompt in provider.prompts[:-1])


def test_collapse_case_trace_and_run_surfaces_carry_no_raw_text() -> None:
    # Redaction (story Security/Privacy): raw diary text, item names, and brands
    # live in provider calls and product data only — never in the sanitized run
    # surfaces the worker persists.
    provider = _collapse_provider(_TWO_ITEM_REPLY)
    context = _context(f"compliments chicken strips and PC dill pickle hummus {_RAW_SENTINEL}")

    ParseStep(provider).run(context)

    sanitized_surfaces = json.dumps(
        {
            "trace": context.trace,
            "assumptions": context.assumptions,
            "source_refs": context.source_refs,
            "validation_errors": context.validation_errors,
        }
    )
    for leaked in (_RAW_SENTINEL, "chicken", "hummus", "Compliments", "PC", "compliments"):
        assert leaked not in sanitized_surfaces
    # The raw text did reach the model (unchanged provider boundary).
    assert all(_RAW_SENTINEL in prompt for prompt in provider.prompts)


def test_reinterpretation_schema_invalid_reply_fails_closed() -> None:
    # The re-ask reply crosses the same untrusted-analyst boundary as a sample:
    # schema-invalid output is rejected and the run fails closed.
    provider = _collapse_provider({"disposition": "parsed", "confidence": "high", "items": []})
    context = _context("compliments chicken strips and PC dill pickle hummus")

    with pytest.raises(StepFailed) as exc:
        ParseStep(provider).run(context)

    assert exc.value.reason == "schema_validation_failed"
    assert context.food_candidates == []


def test_reinterpretation_transient_error_is_retryable() -> None:
    provider = _collapse_provider(LLMTransientError("boom"))
    context = _context("compliments chicken strips and PC dill pickle hummus")

    with pytest.raises(StepError) as exc:
        ParseStep(provider).run(context)

    assert exc.value.message == "provider_transient_error"


def test_hypothesis_kept_when_reinterpretation_confirms_representative() -> None:
    # The re-read may side with the representative sample; the hypothesis is
    # kept (no phantom revision) and the trace says so.
    provider = _collapse_provider(_degenerate(0.9))
    context = _context("compliments chicken strips and PC dill pickle hummus")

    ParseStep(provider).run(context)

    assert "hypothesis_kept" in _outcomes(context)
    session = context.interpretation_session
    assert session is not None
    assert session.hypothesis is not None
    assert session.hypothesis.revision == 0
    assert [c.name for c in context.food_candidates] == ["chicken strips with hummus"]


# --- trigger scope -----------------------------------------------------------------


def test_amount_only_disagreement_does_not_reinterpret() -> None:
    # Quantity jitter is the calibrated agreement signal's concern, not a
    # degenerate item set: no re-ask is spent on it.
    provider = FakeProvider(
        responses=[
            _parsed([{"type": "food", "name": "eggs", "quantity_text": "2", "amount": 2}]),
            _parsed([{"type": "food", "name": "eggs", "quantity_text": "3", "amount": 3}]),
            _parsed([{"type": "food", "name": "eggs", "quantity_text": "2", "amount": 2}]),
        ]
    )
    context = _context("a couple of eggs")

    ParseStep(provider).run(context)

    assert len(provider.prompts) == SELF_CONSISTENCY_NUM_SAMPLES
    assert [c.name for c in context.food_candidates] == ["eggs"]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        # Brand disagreement on the same item.
        (
            [{"type": "food", "name": "hummus", "quantity_text": "", "brand": "PC"}],
            [{"type": "food", "name": "hummus", "quantity_text": ""}],
            True,
        ),
        # Item-count disagreement.
        (
            [
                {"type": "food", "name": "crackers", "quantity_text": ""},
                {"type": "food", "name": "peanut butter", "quantity_text": ""},
            ],
            [{"type": "food", "name": "crackers", "quantity_text": ""}],
            True,
        ),
        # Identity disagreement.
        (
            [{"type": "food", "name": "crackers", "quantity_text": ""}],
            [{"type": "food", "name": "chips", "quantity_text": ""}],
            True,
        ),
        # Amount/unit-only disagreement is not structural.
        (
            [{"type": "food", "name": "eggs", "quantity_text": "2", "amount": 2}],
            [{"type": "food", "name": "eggs", "quantity_text": "3", "amount": 3}],
            False,
        ),
    ],
)
def test_hypothesis_samples_disagree_scope(
    a: list[dict[str, object]], b: list[dict[str, object]], expected: bool
) -> None:
    assert hypothesis_samples_disagree([_result(a), _result(b)]) is expected


def test_single_item_bearing_sample_cannot_attest_disagreement() -> None:
    bearing = _result([{"type": "food", "name": "crackers", "quantity_text": ""}])
    empty = ParseResult.model_validate(
        {"disposition": "needs_clarification", "confidence": 0.3, "items": []}
    )
    assert hypothesis_samples_disagree([bearing, empty]) is False


# --- budget cap and the FTY-326 seam ------------------------------------------------


def _session(provider: FakeProvider, raw_text: str, **kwargs: Any) -> InterpretationSession:
    return InterpretationSession(provider, raw_text, policy=ParsePolicySettings(), **kwargs)


def test_reinterpretation_budget_cap_records_revision_truncated() -> None:
    # The initial disagreement consumes the default budget of one revision call;
    # a further re-ask is refused (no provider call) and traced as truncated —
    # a pathological phrase cannot loop unbounded.
    provider = _collapse_provider(_TWO_ITEM_REPLY)
    context = _context("compliments chicken strips and PC dill pickle hummus")
    session = _session(provider, context.raw_text)

    session.interpret_initial(context)
    prompts_after_initial = len(provider.prompts)

    assert session.reinterpret(context) is None
    assert len(provider.prompts) == prompts_after_initial
    assert _outcomes(context)[-1] == "revision_truncated"
    assert session.hypothesis is not None
    assert session.hypothesis.revision == 1  # the initial disagreement revision stands


def test_budget_of_zero_freezes_nothing_silently() -> None:
    # With the revision budget disabled the session keeps the representative
    # hypothesis but says so in the trace instead of re-asking.
    provider = FakeProvider(responses=[_degenerate(0.95), _TWO_ITEM_REPLY, _degenerate(0.9)])
    context = _context("compliments chicken strips and PC dill pickle hummus")
    session = _session(provider, context.raw_text, max_revision_calls=0)

    session.interpret_initial(context)

    assert len(provider.prompts) == SELF_CONSISTENCY_NUM_SAMPLES
    assert _outcomes(context)[-1] == "revision_truncated"
    assert session.hypothesis is not None
    assert session.hypothesis.revision == 0


def test_evidence_driven_reinterpret_seam_feeds_sanitized_labels_only() -> None:
    # The FTY-326 seam: later steps append sanitized evidence records and
    # re-open interpretation. The re-ask prompt carries the raw text plus the
    # evidence status labels — never fetched content.
    unanimous = _parsed(
        [{"type": "food", "name": "dill pickle hummus", "quantity_text": "2 tbsp", "amount": 2}]
    )
    revised = _parsed(
        [
            {
                "type": "food",
                "name": "dill pickle hummus",
                "quantity_text": "2 tbsp",
                "amount": 2,
                "brand": "PC",
            }
        ]
    )
    provider = FakeProvider(responses=[unanimous, unanimous, revised])
    context = _context(f"PC dill pickle hummus {_RAW_SENTINEL}")
    session = _session(provider, context.raw_text)

    session.interpret_initial(context)
    session.add_evidence(
        EvidenceRecord(tier="usda_fdc", outcome="rejected_brand_mismatch", source_ref="usda_fdc:1")
    )
    result = session.reinterpret(context)

    assert result is not None
    assert result.items[0].brand == "PC"
    reask_prompt = provider.prompts[-1]
    assert "<evidence_status>" in reask_prompt
    assert "usda_fdc: rejected_brand_mismatch (usda_fdc:1)" in reask_prompt
    assert _RAW_SENTINEL in reask_prompt
    # The evidence-driven re-ask also sees the current hypothesis it is
    # revising (FTY-324 decision-point shape): the brandless item as held.
    assert "<current_hypothesis>" in reask_prompt
    assert '1. food "dill pickle hummus", quantity_text "2 tbsp", amount 2' in reask_prompt
    assert "brand_revised" in _outcomes(context)
    assert session.hypothesis is not None
    assert session.hypothesis.revision == 1
    # The matched item kept its run-local id across the revision.
    assert session.hypothesis.items[0].hypothesis_item_id == 1


def test_evidence_labels_are_sanitized_before_provider_egress() -> None:
    # FTY-325 security requirement: provider calls may include raw diary text
    # but nothing else raw. Evidence-ledger fields pass through the
    # decision-trace sanitizers at the prompt seam, so a URL-bearing source_ref
    # sheds its query string, fragment, and secret-looking material before the
    # model sees it.
    unanimous = _parsed(
        [{"type": "food", "name": "dill pickle hummus", "quantity_text": "2 tbsp", "amount": 2}]
    )
    revised = _parsed(
        [
            {
                "type": "food",
                "name": "dill pickle hummus",
                "quantity_text": "2 tbsp",
                "amount": 2,
                "brand": "PC",
            }
        ]
    )
    provider = FakeProvider(responses=[unanimous, unanimous, revised])
    context = _context("PC dill pickle hummus")
    session = _session(provider, context.raw_text)

    session.interpret_initial(context)
    session.add_evidence(
        EvidenceRecord(
            tier="official_web",
            outcome="rejected_nutrition_mismatch",
            source_ref=(
                "official_source:https://brand.example.com/nutrition"
                "?api_key=sk-live1234567890abcdef#frag"
            ),
        )
    )
    session.reinterpret(context)

    reask_prompt = provider.prompts[-1]
    assert (
        "official_web: rejected_nutrition_mismatch"
        " (official_source:https://brand.example.com/nutrition)"
    ) in reask_prompt
    assert "api_key" not in reask_prompt
    assert "sk-live" not in reask_prompt
    assert "#frag" not in reask_prompt


# --- trace observability for every run ----------------------------------------------


def test_every_run_traces_candidate_count_and_per_candidate_labels() -> None:
    # Acceptance: the interpretation step records the hypothesis candidate count
    # and per-candidate sanitized labels (has_brand, amount_kind) on every run —
    # a future degenerate interpretation is diagnosable from the trace alone.
    provider = FakeProvider(
        responses=[
            _parsed(
                [
                    {
                        "type": "food",
                        "name": "big mac",
                        "quantity_text": "1",
                        "amount": 1,
                        "brand": "McDonald's",
                    },
                    {"type": "exercise", "name": "run", "quantity_text": "30 minutes"},
                ]
            )
        ]
        * 2
    )
    context = _context("a big mac and a run")

    ParseStep(provider).run(context)

    entries = _revision_entries(context)
    summary = [e for e in entries if e["outcome"] == "initial_hypothesis" and "result_count" in e]
    assert summary[0]["result_count"] == 2
    per_candidate = [e for e in entries if "candidate_index" in e]
    assert [(e["candidate_index"], e["has_brand"], e["amount_kind"]) for e in per_candidate] == [
        (0, True, "count"),
        (1, False, "unknown"),
    ]

    session = context.interpretation_session
    assert session is not None
    assert session.policy_view.mode == "estimate_first"
    assert session.policy_view.samples_used == 2


def test_blank_brand_is_traced_as_brandless() -> None:
    # The parse contract tells the model to leave generic brands empty and the
    # schema accepts "" — a blank (or whitespace-only) brand must trace
    # has_brand=False so candidate brand state is diagnosable from the labels.
    provider = FakeProvider(
        responses=[
            _parsed(
                [
                    {
                        "type": "food",
                        "name": "banana",
                        "quantity_text": "1",
                        "amount": 1,
                        "brand": "",
                    },
                    {
                        "type": "food",
                        "name": "toast",
                        "quantity_text": "1 slice",
                        "amount": 1,
                        "brand": " ",
                    },
                    {
                        "type": "food",
                        "name": "big mac",
                        "quantity_text": "1",
                        "amount": 1,
                        "brand": "McDonald's",
                    },
                ]
            )
        ]
        * 2
    )
    context = _context("a banana, toast, and a big mac")

    ParseStep(provider).run(context)

    per_candidate = [e for e in _revision_entries(context) if "candidate_index" in e]
    assert [(e["candidate_index"], e["has_brand"]) for e in per_candidate] == [
        (0, False),
        (1, False),
        (2, True),
    ]


def test_deterministic_gate_failure_is_traced_as_validator_outcome() -> None:
    # The plausibility gate is a validator over the hypothesis: same reason and
    # routing as before, now visible in the trace as deterministic_gate_failed.
    provider = FakeProvider(
        responses=[
            _parsed([{"type": "food", "name": "eggs", "quantity_text": "50", "amount": 50.0}])
        ]
        * 2
    )
    context = _context("50 eggs")

    with pytest.raises(NeedsClarification) as exc:
        ParseStep(provider).run(context)

    assert exc.value.reason == "implausible_candidate"
    assert _outcomes(context)[-1] == "deterministic_gate_failed"
    session = context.interpretation_session
    assert session is not None
    assert [question.text for question in session.pending_questions] == [
        question.text for question in context.clarification_questions
    ]


# --- pipeline integration: downstream unchanged pre-FTY-326 -------------------------


def test_default_pipeline_exposes_session_and_downstream_is_unchanged() -> None:
    # The session rides the context; the routed candidates feed the existing
    # steps exactly where parse candidates feed them today (no resolver wired,
    # so food candidates stay unresolved — the pre-FTY-044 composition).
    reply = _parsed(
        [
            {"type": "food", "name": "eggs", "quantity_text": "two", "amount": 2},
            {"type": "exercise", "name": "run", "quantity_text": "30 minutes"},
        ]
    )
    provider = FakeProvider(responses=[reply, reply])
    context = _context("two eggs and a 30 minute run")
    context.weight_kg = 70.0  # the real exercise calculator needs a body weight

    outcome = default_pipeline(provider).run(context)

    assert outcome.outcome is PipelineOutcome.COMPLETED
    assert [c.name for c in context.food_candidates] == ["eggs"]
    assert [c.name for c in context.exercise_candidates] == ["run"]
    session = context.interpretation_session
    assert session is not None
    assert session.hypothesis is not None
    assert [item.candidate.name for item in session.hypothesis.items] == ["eggs", "run"]
    # Run-local ids exist for later steps (FTY-326) without leaking user data.
    assert [item.hypothesis_item_id for item in session.hypothesis.items] == [1, 2]

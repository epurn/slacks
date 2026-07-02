"""Tests for the FTY-169 cross-provider judge tooling (offline).

The router and label-agreement rule are pure and are proven here with fake and
recorded judge outputs — agreement accepts, disagreement queues, and a missing
login fails the batch closed. The live dual-judge run (real ``claude`` + codex
logins) is a maintainer opt-in and is never invoked by these tests, mirroring
FTY-157's live-model opt-in. The codex adapter's parsing and error mapping are
driven through its injectable runner seam, so no real ``codex`` binary is needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.llm.base import ImageInput
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.llm.providers.fake import FakeProvider
from app.schemas.parse import ParsedCandidate
from tests.parse_calibration.harness import load_band
from tests.parse_calibration.judge import (
    _CODEX_ENV_ALLOWLIST,
    FORBIDDEN_KEY_ENV,
    AdjudicationEntry,
    CodexCliProvider,
    CodexResult,
    JudgeLabel,
    adjudicate,
    build_judge_prompt,
    labels_agree,
    provider_judge,
    run_protocol,
)

JUDGE_RUN_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "parse_calibration"
    / "naturalistic_judge_run.json"
)
QUEUE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "parse_calibration"
    / "naturalistic_adjudication_queue.jsonl"
)


def _label(decision: str, items: list[dict[str, object]]) -> JudgeLabel:
    return JudgeLabel.model_validate({"gold_decision": decision, "gold_parse": items})


def _food(name: str, amount: float | None, unit: str | None = None) -> dict[str, object]:
    item: dict[str, object] = {"type": "food", "name": name, "quantity_text": "x"}
    if amount is not None:
        item["amount"] = amount
    if unit is not None:
        item["unit"] = unit
    return item


# --------------------------------------------------------------------------- #
# labels_agree                                                                #
# --------------------------------------------------------------------------- #


def test_identical_estimate_labels_agree() -> None:
    left = _label("estimate", [_food("eggs", 2.0)])
    right = _label("estimate", [_food("eggs", 2.0)])

    assert labels_agree(left, right)


def test_estimate_amounts_within_tolerance_agree() -> None:
    left = _label("estimate", [_food("greek yogurt", 170.0)])
    right = _label("estimate", [_food("Greek Yogurt", 180.0)])  # +5.9%, case differs

    assert labels_agree(left, right)


def test_estimate_amounts_beyond_tolerance_disagree() -> None:
    left = _label("estimate", [_food("beer", 3.0)])
    right = _label("estimate", [_food("beer", 6.0)])  # factor of two apart

    assert not labels_agree(left, right)


def test_different_decisions_disagree() -> None:
    left = _label("estimate", [_food("pasta", 1.0)])
    right = _label("needs_clarification", [_food("pasta", None)])

    assert not labels_agree(left, right)


def test_different_item_sets_disagree() -> None:
    left = _label("estimate", [_food("salad", 1.0), _food("dressing", 2.0)])
    right = _label("estimate", [_food("salad", 1.0)])

    assert not labels_agree(left, right)


def test_missing_amount_only_agrees_with_missing_amount() -> None:
    left = _label("estimate", [_food("toast", None)])
    right = _label("estimate", [_food("toast", 1.0)])

    assert not labels_agree(left, right)


def test_needs_clarification_pair_agrees_regardless_of_placeholder_parse() -> None:
    # Both defer the portion; the parse is a placeholder, so item differences do
    # not split the queue.
    left = _label("needs_clarification", [_food("chips", None)])
    right = _label("needs_clarification", [_food("chips", None), _food("dip", None)])

    assert labels_agree(left, right)


# --------------------------------------------------------------------------- #
# adjudicate / run_protocol                                                   #
# --------------------------------------------------------------------------- #


def test_agreement_produces_accepted_label_with_claude_parse() -> None:
    claude = _label("estimate", [_food("cheese", 2.5)])
    codex = _label("estimate", [_food("cheese", 2.0)])  # within tolerance

    verdict = adjudicate("2-3 slices of cheese", claude, codex)

    assert verdict.queued is None
    assert verdict.accepted is not None
    assert verdict.accepted.gold_decision == "estimate"
    # The committed parse is the Claude judge's, deterministically.
    assert verdict.accepted.gold_parse[0].amount == 2.5


def test_disagreement_queues_both_judge_outputs() -> None:
    claude = _label("estimate", [_food("pasta", 1.0)])
    codex = _label("needs_clarification", [_food("pasta", None)])

    verdict = adjudicate("some pasta with a bit of sauce", claude, codex)

    assert verdict.accepted is None
    assert verdict.queued is not None
    assert verdict.queued.claude == claude
    assert verdict.queued.codex == codex
    assert "claude=estimate" in verdict.queued.reason


def test_run_protocol_routes_and_reports_agreement_rate() -> None:
    inputs = ["agree-1", "agree-2", "contested"]
    claude_labels = {
        "agree-1": _label("estimate", [_food("eggs", 2.0)]),
        "agree-2": _label("needs_clarification", [_food("chips", None)]),
        "contested": _label("estimate", [_food("beer", 3.0)]),
    }
    codex_labels = {
        "agree-1": _label("estimate", [_food("eggs", 2.0)]),
        "agree-2": _label("needs_clarification", [_food("chips", None)]),
        "contested": _label("estimate", [_food("beer", 6.0)]),
    }

    result = run_protocol(inputs, lambda t: claude_labels[t], lambda t: codex_labels[t])

    assert len(result.accepted) == 2
    assert len(result.queue) == 1
    assert result.agreement_rate == pytest.approx(2 / 3)


def test_run_protocol_fails_closed_when_a_judge_has_no_login() -> None:
    def no_login_judge(_: str) -> JudgeLabel:
        raise LLMConfigurationError("codex is not authenticated; run 'codex login'")

    ok_judge = lambda t: _label("estimate", [_food("eggs", 2.0)])  # noqa: E731

    with pytest.raises(LLMConfigurationError, match="not authenticated"):
        run_protocol(["anything"], ok_judge, no_login_judge)


# --------------------------------------------------------------------------- #
# Recorded judge run reproduces the committed seed + queue (offline protocol)  #
# --------------------------------------------------------------------------- #


def test_recorded_judge_run_reproduces_committed_seed_and_queue() -> None:
    run = json.loads(JUDGE_RUN_PATH.read_text(encoding="utf-8"))
    records = run["records"]
    by_input = {r["input"]: r for r in records}

    def claude(text: str) -> JudgeLabel:
        return JudgeLabel.model_validate(by_input[text]["claude"])

    def codex(text: str) -> JudgeLabel:
        return JudgeLabel.model_validate(by_input[text]["codex"])

    result = run_protocol([r["input"] for r in records], claude, codex)

    # Accepted agreements reproduce the committed judged examples exactly.
    committed = {
        example.input: example
        for example in load_band("naturalistic")
        if example.source_kind == "recorded_stand_in"
    }
    assert {label.input for label in result.accepted} == set(committed)
    for label in result.accepted:
        example = committed[label.input]
        assert label.gold_decision == example.gold_decision
        assert _dump(label.gold_parse) == _dump(example.gold_parse)

    # Disagreements reproduce the committed adjudication queue exactly.
    committed_queue = [
        AdjudicationEntry.model_validate(json.loads(line))
        for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert result.queue == committed_queue

    # The stand-in run's recorded agreement rate the README documents (a fixture
    # property, not an observed live inter-judge rate).
    assert result.agreement_rate == pytest.approx(12 / 14)


def _dump(items: list[ParsedCandidate]) -> list[dict[str, object]]:
    return [item.model_dump(exclude_none=True) for item in items]


# --------------------------------------------------------------------------- #
# provider_judge over a fake provider                                         #
# --------------------------------------------------------------------------- #


def test_provider_judge_returns_validated_label() -> None:
    payload = {"gold_decision": "estimate", "gold_parse": [_food("eggs", 2.0)]}
    fake = FakeProvider(responses=[payload])

    judge = provider_judge(fake)
    label = judge("2 eggs")

    assert isinstance(label, JudgeLabel)
    assert label.gold_decision == "estimate"
    assert build_judge_prompt("2 eggs") in fake.prompts[0]


def test_provider_judge_rejects_schema_invalid_reply() -> None:
    fake = FakeProvider(responses=[{"gold_decision": "maybe", "gold_parse": []}])

    with pytest.raises(StructuredOutputValidationError):
        provider_judge(fake)("2 eggs")


# --------------------------------------------------------------------------- #
# CodexCliProvider — no paid key, prompt off argv, parsing + error mapping     #
# --------------------------------------------------------------------------- #


def test_codex_env_allowlist_never_forwards_a_paid_key() -> None:
    # The whole FTY-086 point: the codex judge rides the login session only.
    assert _CODEX_ENV_ALLOWLIST.isdisjoint(FORBIDDEN_KEY_ENV)
    assert "OPENAI_API_KEY" not in _CODEX_ENV_ALLOWLIST


def test_codex_invocation_keeps_prompt_off_argv() -> None:
    provider = CodexCliProvider(timeout_seconds=1.0, max_retries=0)

    invocation = provider.build_invocation("2 eggs and a run", JudgeLabel)

    assert "2 eggs and a run" not in " ".join(invocation.argv)
    assert "2 eggs and a run" in invocation.stdin
    # Headless, sandboxed default with no tool/host access.
    assert invocation.argv[0] == "codex"
    assert "exec" in invocation.argv


def test_codex_provider_parses_structured_reply() -> None:
    payload = json.dumps({"gold_decision": "estimate", "gold_parse": [_food("eggs", 2.0)]})

    def runner(_invocation: object, *, timeout_seconds: float) -> CodexResult:
        return CodexResult(returncode=0, stdout=f"```json\n{payload}\n```", stderr="")

    provider = CodexCliProvider(timeout_seconds=1.0, max_retries=0, runner=runner)
    label = provider.structured_completion(build_judge_prompt("2 eggs"), JudgeLabel)

    assert label.gold_decision == "estimate"


def test_codex_provider_maps_missing_login_to_configuration_error() -> None:
    def runner(_invocation: object, *, timeout_seconds: float) -> CodexResult:
        return CodexResult(returncode=1, stdout="", stderr="Not logged in. Please run codex login")

    provider = CodexCliProvider(timeout_seconds=1.0, max_retries=0, runner=runner)

    with pytest.raises(LLMConfigurationError, match="not authenticated"):
        provider.structured_completion(build_judge_prompt("x"), JudgeLabel)


def test_codex_provider_maps_missing_binary_to_configuration_error() -> None:
    def runner(_invocation: object, *, timeout_seconds: float) -> CodexResult:
        raise FileNotFoundError

    provider = CodexCliProvider(timeout_seconds=1.0, max_retries=0, runner=runner)

    with pytest.raises(LLMConfigurationError, match="codex binary not found"):
        provider.structured_completion(build_judge_prompt("x"), JudgeLabel)


def test_codex_provider_maps_rate_limit_to_transient_error() -> None:
    def runner(_invocation: object, *, timeout_seconds: float) -> CodexResult:
        return CodexResult(returncode=1, stdout="", stderr="rate limit exceeded")

    provider = CodexCliProvider(timeout_seconds=1.0, max_retries=0, runner=runner)

    with pytest.raises(LLMTransientError):
        provider.structured_completion(build_judge_prompt("x"), JudgeLabel)


def test_codex_provider_rejects_non_json_body() -> None:
    def runner(_invocation: object, *, timeout_seconds: float) -> CodexResult:
        return CodexResult(returncode=0, stdout="I think it was eggs", stderr="")

    provider = CodexCliProvider(timeout_seconds=1.0, max_retries=0, runner=runner)

    with pytest.raises(LLMResponseError):
        provider.structured_completion(build_judge_prompt("x"), JudgeLabel)


def test_codex_provider_refuses_image_input() -> None:
    provider = CodexCliProvider(timeout_seconds=1.0, max_retries=0)

    image = ImageInput(data=b"\x89PNG", media_type="image/png")
    with pytest.raises(LLMConfigurationError, match="does not support image input"):
        provider._complete("x", JudgeLabel, images=[image], timeout_seconds=1.0)

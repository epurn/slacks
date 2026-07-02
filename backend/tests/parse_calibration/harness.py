"""Offline parse-calibration evaluation harness (FTY-157, extended by FTY-158/159).

The harness scores a pluggable clarify/estimate signal over the committed
synthetic calibration set. It is intentionally test-only: no production parse
code is *changed*, and the default signals use recorded fixture fields so
backend verification stays deterministic and offline.

FTY-158 adds the self-consistency signals: each fixture example carries N=3
recorded parse samples (synthetic-by-construction stand-ins for temperature>0
sampling), and the recorded agreement/hybrid signals score them through the
*production* metric (``app.estimator.self_consistency``) — including the
early-stop rule — so the offline evaluation computes exactly what the live
sampler would. The live, provider-backed variant
(:func:`live_self_consistency_signal`) is the opt-in mode and is never invoked
by default verification.

FTY-159 adds the signal **bake-off** and the **data-calibrated operating
point**: :func:`run_bake_off` scores every recorded signal over the combined
(synthetic + naturalistic) labeled set, selects the winner on the
risk-coverage curve at the target answered precision, and derives the clarify
threshold the production gate uses (:func:`select_operating_point`). The
committed result is ``calibration_summary.json``; the production constant
(``app.estimator.clarify_policy.NL_PARSE_CLARIFY_POLICY``) must equal the
derived point — ``tests/test_clarify_calibration.py`` is the regression gate.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.estimator.self_consistency import (
    SelfConsistencySignal,
    apply_early_stop,
    evaluate_self_consistency,
)
from app.llm.base import Provider
from app.schemas.parse import ParsedCandidate, ParseDisposition, ParseResult

Decision = Literal["estimate", "needs_clarification"]
DifficultyBand = Literal["unambiguous", "inferable", "indeterminate"]

#: Which distribution band an example belongs to. ``synthetic`` is the FTY-157
#: clean-by-construction set; ``naturalistic`` (FTY-169) is the messy,
#: real-world-*style* band labeled per the cross-provider judge protocol
#: (``README.md``).
DistributionBand = Literal["synthetic", "naturalistic"]

#: How an example's gold label was produced. ``synthetic_by_construction`` is the
#: FTY-157 known-parse-then-render path. The naturalistic band (FTY-169) uses
#: ``authored_naturalistic`` (an author-constructed unambiguous case,
#: agreement-trivial by construction) or ``recorded_stand_in`` (an
#: author-constructed label whose recorded two-judge outputs exist only to pin
#: the router offline — no live judge produced it). ``cross_provider_judge`` is
#: **reserved** for labels the live independent Claude + GPT-5.5 protocol
#: actually produced (per ``README.md``); no committed example carries it until
#: the maintainer's live pass lands. No committed label is ever derived from
#: real user data.
LabelSourceKind = Literal[
    "synthetic_by_construction",
    "authored_naturalistic",
    "recorded_stand_in",
    "cross_provider_judge",
]

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "parse_calibration" / "examples.jsonl"
)
NATURALISTIC_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "parse_calibration"
    / "naturalistic_examples.jsonl"
)
BASELINE_SUMMARY_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "parse_calibration" / "baseline_summary.json"
)
SELF_CONSISTENCY_SUMMARY_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "parse_calibration"
    / "self_consistency_summary.json"
)
CALIBRATION_SUMMARY_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "parse_calibration"
    / "calibration_summary.json"
)

#: The retired pre-FTY-159 production gate (verbalized confidence vs 0.45).
#: Kept as the harness's *baseline reference* operating point: the FTY-157/158
#: committed summaries pin their metrics at it, and the FTY-159 calibrated
#: decision's measured improvement is reported against it.
DEFAULT_OPERATING_THRESHOLD = 0.45
DEFAULT_RISK_THRESHOLDS = (0.0, 0.3, 0.45, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)

#: The answered-precision target the FTY-159 operating point is derived for: of
#: the events the gate estimates, at least this fraction must be gold-estimate.
#: Precision (not raw correct-decision rate) is the calibration target because
#: under-asking — confidently estimating an input that genuinely needed a
#: question — is the worse failure for an honest-count app (a silently wrong
#: total), while an over-ask costs one avoidable question. Maximising coverage
#: subject to this floor then minimises over-asking. 0.99 is the tightest floor
#: the combined labeled set supports with a real margin band; the residual
#: answered errors are the consistent-but-wrong sampling class, self-
#: consistency's documented blind spot.
TARGET_ANSWERED_PRECISION = 0.99

#: Number of recorded self-consistency samples each committed fixture example
#: carries — matches the production default N
#: (``app.estimator.self_consistency.SELF_CONSISTENCY_NUM_SAMPLES``).
RECORDED_SAMPLE_COUNT = 3


class BaselineSignalRecord(BaseModel):
    """Recorded, offline stand-in for the current verbalized-confidence signal."""

    model_config = ConfigDict(extra="forbid")

    disposition: ParseDisposition
    confidence: float = Field(ge=0.0, le=1.0)


class LabeledParseExample(BaseModel):
    """One synthetic calibration/evaluation example."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    difficulty: DifficultyBand
    #: Distribution band. Defaults to ``synthetic`` so the FTY-157 fixture (which
    #: predates the field) validates unchanged; the FTY-169 naturalistic fixture
    #: sets it explicitly.
    band: DistributionBand = "synthetic"
    source_kind: LabelSourceKind
    source_template: str = Field(min_length=1, max_length=80)
    input: str = Field(min_length=1, max_length=240)
    gold_decision: Decision
    gold_parse: list[ParsedCandidate] = Field(min_length=1, max_length=32)
    baseline: BaselineSignalRecord
    #: Recorded temperature>0 parse samples for the FTY-158 self-consistency
    #: signals — synthetic by construction, like everything else in the fixture.
    #: Each validates as a full ``ParseResult`` so the production agreement
    #: metric consumes them unchanged. Optional so hand-built examples in metric
    #: unit tests need not carry samples; the recorded consistency signals
    #: require them.
    samples: list[ParseResult] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True)
class SignalResult:
    """A clarify/estimate signal result.

    ``score`` is interpreted as confidence that the example should be estimated.
    When ``score`` is present, the abstention threshold decides estimate vs ask.
    ``decision`` lets callers provide a direct decision for one-point evaluation
    or for signals that do not expose a score.
    """

    score: float | None = None
    decision: Decision | None = None

    def __post_init__(self) -> None:
        if self.score is None and self.decision is None:
            msg = "SignalResult requires a score or a decision"
            raise ValueError(msg)
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            msg = "SignalResult.score must be in [0, 1]"
            raise ValueError(msg)


class ExampleSignal(Protocol):
    """Callable signal over a labeled example."""

    def __call__(self, example: LabeledParseExample) -> SignalResult: ...


class TextSignal(Protocol):
    """Callable signal over only the raw user input text."""

    def __call__(self, raw_text: str) -> SignalResult: ...


@dataclass(frozen=True)
class OperatingMetrics:
    """Decision metrics at one clarify/estimate operating point."""

    threshold: float | None
    total: int
    gold_estimate: int
    gold_ask: int
    answered: int
    asked: int
    correct_estimates: int
    over_ask: int
    under_ask: int

    @property
    def coverage(self) -> float:
        return _rate(self.answered, self.total)

    @property
    def answered_accuracy(self) -> float | None:
        if self.answered == 0:
            return None
        return _rate(self.correct_estimates, self.answered)

    @property
    def correct_decision_rate(self) -> float:
        correct = self.total - self.over_ask - self.under_ask
        return _rate(correct, self.total)

    @property
    def over_ask_rate(self) -> float:
        return _rate(self.over_ask, self.gold_estimate)

    @property
    def under_ask_rate(self) -> float:
        return _rate(self.under_ask, self.gold_ask)

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            "threshold": self.threshold,
            "total": self.total,
            "gold_estimate": self.gold_estimate,
            "gold_ask": self.gold_ask,
            "answered": self.answered,
            "asked": self.asked,
            "coverage": _round(self.coverage),
            "answered_accuracy": (
                None if self.answered_accuracy is None else _round(self.answered_accuracy)
            ),
            "correct_decision_rate": _round(self.correct_decision_rate),
            "correct_estimates": self.correct_estimates,
            "over_ask": self.over_ask,
            "over_ask_rate": _round(self.over_ask_rate),
            "under_ask": self.under_ask,
            "under_ask_rate": _round(self.under_ask_rate),
        }


@dataclass(frozen=True)
class EvaluationSummary:
    """Machine-readable parse calibration summary."""

    fixture: str
    signal_name: str
    operating_threshold: float
    total_examples: int
    by_difficulty: dict[str, OperatingMetrics]
    operating: OperatingMetrics
    risk_coverage_curve: list[OperatingMetrics]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "signal_name": self.signal_name,
            "operating_threshold": self.operating_threshold,
            "total_examples": self.total_examples,
            "by_difficulty": {
                band: metrics.to_dict() for band, metrics in self.by_difficulty.items()
            },
            "operating": self.operating.to_dict(),
            "risk_coverage_curve": [point.to_dict() for point in self.risk_coverage_curve],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def human_table(self) -> str:
        lines = [
            f"signal: {self.signal_name}",
            f"fixture: {self.fixture}",
            f"examples: {self.total_examples}",
            "",
            "Risk-coverage curve",
            "threshold  coverage  answered_accuracy  over_ask  under_ask",
        ]
        for point in self.risk_coverage_curve:
            accuracy = _format_optional_rate(point.answered_accuracy)
            lines.append(
                f"{_format_threshold(point.threshold):>9}  "
                f"{point.coverage:>8.1%}  "
                f"{accuracy:>17}  "
                f"{point.over_ask_rate:>8.1%}  "
                f"{point.under_ask_rate:>9.1%}"
            )

        lines.extend(
            [
                "",
                "Operating point",
                "band            examples  coverage  correct  over_ask  under_ask",
            ]
        )
        for band, metrics in {"overall": self.operating, **self.by_difficulty}.items():
            lines.append(
                f"{band:<15}  "
                f"{metrics.total:>8}  "
                f"{metrics.coverage:>8.1%}  "
                f"{metrics.correct_decision_rate:>7.1%}  "
                f"{metrics.over_ask_rate:>8.1%}  "
                f"{metrics.under_ask_rate:>9.1%}"
            )
        return "\n".join(lines)


def load_examples(path: Path = FIXTURE_PATH) -> list[LabeledParseExample]:
    """Load and validate the JSONL calibration fixture."""

    examples: list[LabeledParseExample] = []
    with path.open(encoding="utf-8") as fixture:
        for line_number, line in enumerate(fixture, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                msg = f"{path}:{line_number}: invalid JSON"
                raise ValueError(msg) from exc
            try:
                examples.append(LabeledParseExample.model_validate(payload))
            except ValueError as exc:
                msg = f"{path}:{line_number}: invalid calibration example"
                raise ValueError(msg) from exc

    ids = [example.id for example in examples]
    if len(set(ids)) != len(ids):
        msg = "calibration fixture contains duplicate ids"
        raise ValueError(msg)
    return examples


#: The band selector accepted by band-aware evaluation: one committed fixture,
#: or ``combined`` for the synthetic + naturalistic union FTY-159 calibrates on.
BandSelector = Literal["synthetic", "naturalistic", "combined"]

_BAND_FIXTURES: dict[str, Path] = {
    "synthetic": FIXTURE_PATH,
    "naturalistic": NATURALISTIC_FIXTURE_PATH,
}


def load_band(band: BandSelector) -> list[LabeledParseExample]:
    """Load the committed examples for a band (``combined`` unions both fixtures).

    Each fixture is validated by :func:`load_examples`; the combined set is
    checked for cross-fixture id collisions so a run can report synthetic vs
    naturalistic vs combined without silently dropping a shadowed example.
    """

    if band == "combined":
        examples = load_examples(FIXTURE_PATH) + load_examples(NATURALISTIC_FIXTURE_PATH)
        ids = [example.id for example in examples]
        if len(set(ids)) != len(ids):
            msg = "combined calibration set contains duplicate ids across bands"
            raise ValueError(msg)
        return examples
    return load_examples(_BAND_FIXTURES[band])


def adapt_text_signal(signal: TextSignal) -> ExampleSignal:
    """Wrap a raw-text signal so it can be evaluated against labeled examples."""

    def _wrapped(example: LabeledParseExample) -> SignalResult:
        return signal(example.input)

    return _wrapped


def verbalized_confidence_baseline(example: LabeledParseExample) -> SignalResult:
    """Recorded baseline for the current verbalized-confidence-vs-0.45 gate."""

    if example.baseline.disposition is ParseDisposition.PARSED:
        return SignalResult(score=example.baseline.confidence)
    return SignalResult(decision="needs_clarification")


def recorded_agreement_signal(example: LabeledParseExample) -> SignalResult:
    """FTY-158 pure sampling-agreement signal over the recorded samples."""

    return _signal_result(_recorded_signal(example), use_hybrid=False)


def recorded_hybrid_signal(example: LabeledParseExample) -> SignalResult:
    """FTY-158 hybrid (agreement + verbalized) signal over the recorded samples."""

    return _signal_result(_recorded_signal(example), use_hybrid=True)


def live_self_consistency_signal(provider: Provider, *, use_hybrid: bool = True) -> TextSignal:
    """Provider-backed self-consistency signal — the opt-in *live* evaluation mode.

    Wire it up with ``build_provider(load_llm_settings())`` and pass the result
    to :func:`evaluate_signal` via :func:`adapt_text_signal`. Never invoked by
    default verification: it samples a real model N times per example and costs
    real tokens. The recorded signals above are the deterministic default.
    """

    def _signal(raw_text: str) -> SignalResult:
        return _signal_result(evaluate_self_consistency(provider, raw_text), use_hybrid=use_hybrid)

    return _signal


def _recorded_signal(example: LabeledParseExample) -> SelfConsistencySignal:
    """Compute the production signal over an example's recorded samples.

    Applies the production early-stop rule to the recorded sample list first, so
    the offline score is exactly what the live sampler would have computed
    (a unanimous first window never draws — here, never scores — the rest).
    """

    if not example.samples:
        msg = f"example {example.id} has no recorded self-consistency samples"
        raise ValueError(msg)
    return SelfConsistencySignal.from_samples(apply_early_stop(example.samples))


def _signal_result(signal: SelfConsistencySignal, *, use_hybrid: bool) -> SignalResult:
    """Map the production signal onto the harness's score/decision shape.

    A sample set that never parsed is a direct clarify *decision* (fail closed):
    its agreement can be a perfect 1.0 — unanimously asking — which must not be
    read as estimate-confidence by the threshold sweep.
    """

    if signal.all_non_parsed:
        return SignalResult(decision="needs_clarification")
    return SignalResult(score=signal.hybrid if use_hybrid else signal.agreement)


def evaluate_signal(
    examples: Sequence[LabeledParseExample],
    signal: ExampleSignal,
    *,
    signal_name: str,
    fixture_name: str,
    operating_threshold: float = DEFAULT_OPERATING_THRESHOLD,
    risk_thresholds: Iterable[float] = DEFAULT_RISK_THRESHOLDS,
) -> EvaluationSummary:
    """Evaluate a signal and return machine-readable metrics."""

    if not examples:
        msg = "at least one calibration example is required"
        raise ValueError(msg)
    if not 0.0 <= operating_threshold <= 1.0:
        msg = "operating_threshold must be in [0, 1]"
        raise ValueError(msg)

    results = [(example, signal(example)) for example in examples]
    thresholds = _thresholds(results, operating_threshold, risk_thresholds)
    operating = _metrics_at_threshold(results, operating_threshold)
    by_difficulty = {
        band: _metrics_at_threshold(
            [(example, result) for example, result in results if example.difficulty == band],
            operating_threshold,
        )
        for band in ("unambiguous", "inferable", "indeterminate")
    }
    risk_curve = [_metrics_at_threshold(results, threshold) for threshold in thresholds]
    return EvaluationSummary(
        fixture=fixture_name,
        signal_name=signal_name,
        operating_threshold=operating_threshold,
        total_examples=len(examples),
        by_difficulty=by_difficulty,
        operating=operating,
        risk_coverage_curve=risk_curve,
    )


#: The recorded signals the harness can evaluate offline, by CLI name.
RECORDED_SIGNALS: dict[str, tuple[ExampleSignal, str]] = {
    "baseline": (
        verbalized_confidence_baseline,
        "recorded_verbalized_confidence_threshold_0_45",
    ),
    "agreement": (
        recorded_agreement_signal,
        "recorded_self_consistency_agreement_n3_window2",
    ),
    "hybrid": (
        recorded_hybrid_signal,
        "recorded_hybrid_consistency_verbalized_n3_window2",
    ),
}


def evaluate_recorded(signal: str, path: Path = FIXTURE_PATH) -> EvaluationSummary:
    """Evaluate one of the committed recorded signals over the fixture."""

    example_signal, signal_name = RECORDED_SIGNALS[signal]
    examples = load_examples(path)
    return evaluate_signal(
        examples,
        example_signal,
        signal_name=signal_name,
        fixture_name=str(path.relative_to(Path(__file__).resolve().parents[2])),
    )


def evaluate_recorded_band(
    signal: str,
    band: BandSelector,
    *,
    operating_threshold: float = DEFAULT_OPERATING_THRESHOLD,
) -> EvaluationSummary:
    """Evaluate a committed recorded signal over one band (or the combined set).

    Both bands carry recorded self-consistency ``samples`` (the naturalistic
    band's are FTY-159 author-constructed stand-ins, like the rest of that
    seed), so every recorded signal scores every band. FTY-159 calibrates the
    operating point over ``combined``.
    """

    example_signal, signal_name = RECORDED_SIGNALS[signal]
    examples = load_band(band)
    return evaluate_signal(
        examples,
        example_signal,
        signal_name=f"{signal_name}[{band}]",
        fixture_name=f"parse_calibration:{band}",
        operating_threshold=operating_threshold,
    )


@dataclass(frozen=True)
class OperatingPointSelection:
    """A signal's derived clarify threshold at the target answered precision.

    ``feasible_score`` is the lowest observed signal score whose
    threshold-sweep metrics meet the precision target at maximal coverage;
    ``margin_low`` is the highest observed score strictly below it. The
    operating ``threshold`` is their midpoint, so the committed cutoff sits in
    the middle of the empirical margin band rather than exactly on an observed
    score (a knife-edge a float wiggle could cross).
    """

    signal: str
    target_precision: float
    threshold: float
    feasible_score: float
    margin_low: float
    metrics: OperatingMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "target_precision": self.target_precision,
            "threshold": self.threshold,
            "feasible_score": self.feasible_score,
            "margin_low": self.margin_low,
            "operating": self.metrics.to_dict(),
        }


def select_operating_point(
    examples: Sequence[LabeledParseExample],
    signal: ExampleSignal,
    *,
    signal_name: str,
    target_precision: float = TARGET_ANSWERED_PRECISION,
) -> OperatingPointSelection | None:
    """Derive a signal's clarify threshold for the target answered precision.

    Sweeps every observed score as a candidate threshold, keeps the candidates
    whose answered precision meets the target (with at least one answered
    example), and picks the one with maximal coverage — i.e. the fewest
    questions the signal can ask while keeping estimates this reliable. The
    returned threshold is the midpoint between that score and the next observed
    score below it (see :class:`OperatingPointSelection`). Returns ``None``
    when no observed threshold meets the target — an infeasible signal cannot
    be wired at this target, which the bake-off treats as losing.
    """

    results = [(example, signal(example)) for example in examples]
    observed = sorted({result.score for _, result in results if result.score is not None})
    feasible: list[tuple[float, OperatingMetrics]] = []
    for candidate in observed:
        metrics = _metrics_at_threshold(results, candidate)
        accuracy = metrics.answered_accuracy
        if metrics.answered > 0 and accuracy is not None and accuracy >= target_precision:
            feasible.append((candidate, metrics))
    if not feasible:
        return None

    score, _ = max(feasible, key=lambda pair: (pair[1].coverage, -pair[0]))
    below = [value for value in observed if value < score]
    margin_low = max(below) if below else 0.0
    threshold = round((score + margin_low) / 2, 6)
    return OperatingPointSelection(
        signal=signal_name,
        target_precision=target_precision,
        threshold=threshold,
        feasible_score=round(score, 6),
        margin_low=round(margin_low, 6),
        metrics=_metrics_at_threshold(results, threshold),
    )


def run_bake_off(
    band: BandSelector = "combined",
    *,
    target_precision: float = TARGET_ANSWERED_PRECISION,
) -> dict[str, Any]:
    """Run the FTY-159 signal bake-off and derive the calibrated operating point.

    Every recorded signal (verbalized baseline, FTY-158 self-consistency
    agreement, hybrid) is scored over ``band`` and gets an operating point
    derived at the target precision (:func:`select_operating_point`). The
    winner is the feasible signal with the highest correct-decision rate at its
    derived point (coverage breaks ties). The result also reports the winner's
    full summary at the calibrated threshold, its per-band operating metrics,
    and the measured improvement over the retired production gate (recorded
    verbalized confidence vs ``DEFAULT_OPERATING_THRESHOLD``).
    """

    examples = load_band(band)
    selections: dict[str, OperatingPointSelection | None] = {}
    for key, (example_signal, signal_name) in RECORDED_SIGNALS.items():
        selections[key] = select_operating_point(
            examples,
            example_signal,
            signal_name=signal_name,
            target_precision=target_precision,
        )

    feasible = {key: sel for key, sel in selections.items() if sel is not None}
    if not feasible:
        msg = f"no recorded signal meets answered precision {target_precision} on {band}"
        raise ValueError(msg)
    winner_key = max(
        feasible,
        key=lambda key: (
            feasible[key].metrics.correct_decision_rate,
            feasible[key].metrics.coverage,
        ),
    )
    winner = feasible[winner_key]

    baseline_reference = evaluate_recorded_band("baseline", band).operating
    winner_summary = evaluate_recorded_band(winner_key, band, operating_threshold=winner.threshold)
    per_band: dict[str, Any] = {}
    if band == "combined":
        for sub_band in ("synthetic", "naturalistic"):
            per_band[sub_band] = evaluate_recorded_band(
                winner_key, sub_band, operating_threshold=winner.threshold
            ).operating.to_dict()

    return {
        "band": band,
        "total_examples": len(examples),
        "target_answered_precision": target_precision,
        "baseline_reference": {
            "signal": RECORDED_SIGNALS["baseline"][1],
            "threshold": DEFAULT_OPERATING_THRESHOLD,
            "operating": baseline_reference.to_dict(),
        },
        "selections": {
            key: (None if sel is None else sel.to_dict()) for key, sel in selections.items()
        },
        "winner": {
            "signal": winner_key,
            "signal_name": winner.signal,
            "threshold": winner.threshold,
            "summary": winner_summary.to_dict(),
            "per_band": per_band,
        },
    }


def evaluate_recorded_baseline(path: Path = FIXTURE_PATH) -> EvaluationSummary:
    """Evaluate the committed recorded baseline fixture signal."""

    return evaluate_recorded("baseline", path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the parse calibration harness.")
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument(
        "--band",
        choices=("synthetic", "naturalistic", "combined"),
        default=None,
        help=(
            "score a committed band instead of --fixture: synthetic (FTY-157), "
            "naturalistic (FTY-169), or combined. Overrides --fixture."
        ),
    )
    parser.add_argument(
        "--signal",
        choices=sorted(RECORDED_SIGNALS),
        default="baseline",
        help="which recorded signal to evaluate (default: baseline)",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument(
        "--bake-off",
        action="store_true",
        help=(
            "run the FTY-159 signal bake-off over --band (default combined): "
            "derive each signal's operating point at the target precision, pick "
            "the winner, and print (or --write-summary) the calibration JSON"
        ),
    )
    parser.add_argument(
        "--write-baseline",
        type=Path,
        help="write the recorded baseline summary JSON to this path",
    )
    parser.add_argument(
        "--write-summary",
        type=Path,
        help="write the selected signal's (or bake-off's) summary JSON to this path",
    )
    args = parser.parse_args(argv)

    if args.bake_off:
        bake_off = run_bake_off(args.band or "combined")
        payload = json.dumps(bake_off, indent=2, sort_keys=True) + "\n"
        if args.write_summary is not None:
            args.write_summary.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0

    if args.band is not None:
        summary = evaluate_recorded_band(args.signal, args.band)
    else:
        summary = evaluate_recorded(args.signal, args.fixture)
    if args.write_baseline is not None:
        args.write_baseline.write_text(
            evaluate_recorded("baseline", args.fixture).to_json(), encoding="utf-8"
        )
    if args.write_summary is not None:
        args.write_summary.write_text(summary.to_json(), encoding="utf-8")
    if args.write_baseline is None and args.write_summary is None:
        if args.json:
            print(summary.to_json(), end="")
        else:
            print(summary.human_table())
    return 0


def _thresholds(
    results: Sequence[tuple[LabeledParseExample, SignalResult]],
    operating_threshold: float,
    risk_thresholds: Iterable[float],
) -> list[float]:
    values = {operating_threshold}
    values.update(risk_thresholds)
    for _, result in results:
        if result.score is not None:
            values.add(result.score)
    return sorted(value for value in values if 0.0 <= value <= 1.0)


def _metrics_at_threshold(
    results: Sequence[tuple[LabeledParseExample, SignalResult]], threshold: float | None
) -> OperatingMetrics:
    total = len(results)
    gold_estimate = sum(1 for example, _ in results if example.gold_decision == "estimate")
    gold_ask = total - gold_estimate
    answered = 0
    correct_estimates = 0
    over_ask = 0
    under_ask = 0

    for example, result in results:
        predicted = _decision_for(result, threshold)
        if predicted == "estimate":
            answered += 1
            if example.gold_decision == "estimate":
                correct_estimates += 1
            else:
                under_ask += 1
        elif example.gold_decision == "estimate":
            over_ask += 1

    return OperatingMetrics(
        threshold=threshold,
        total=total,
        gold_estimate=gold_estimate,
        gold_ask=gold_ask,
        answered=answered,
        asked=total - answered,
        correct_estimates=correct_estimates,
        over_ask=over_ask,
        under_ask=under_ask,
    )


def _decision_for(result: SignalResult, threshold: float | None) -> Decision:
    if result.score is not None and threshold is not None:
        return "estimate" if result.score >= threshold else "needs_clarification"
    if result.decision is None:
        msg = "decision-only evaluation requires SignalResult.decision"
        raise ValueError(msg)
    return result.decision


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _round(value: float) -> float:
    return round(value, 6)


def _format_threshold(threshold: float | None) -> str:
    if threshold is None:
        return "decision"
    return f"{threshold:.2f}"


def _format_optional_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


if __name__ == "__main__":
    raise SystemExit(main())

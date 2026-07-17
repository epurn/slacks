"""Self-consistency confidence signal for the NL parse (FTY-158, ADR 0003 Layer B).

The verbalized ``confidence`` the parse model self-reports is weak and
overconfident on instruction-tuned models, and Slacks's plan-covered provider
(Claude) exposes no token log-probabilities, so logprob-based confidence is
unavailable. The viable strong signal is **sampling agreement**: parse the same
input N times (the provider samples at its default temperature > 0), and measure
how much the returned candidates agree. High agreement → the parse is stable and
can be trusted as an estimate; high disagreement → the input is genuinely
ambiguous and the safe route is a clarifying question (fail closed). See
``docs/adr/0003-estimator-confidence-clarification.md`` for the decision record
and citations (SelfCheckGPT; Xiong et al., ICLR 2024; Li et al., ICLR 2024).

This module produces the *signal only*. It is validated offline against the
FTY-157 calibration harness (``tests/parse_calibration``). FTY-159 wired it
into the live clarify gate: the parse step samples through
:func:`collect_parse_samples` and compares the hybrid score against the
data-calibrated operating point
(:data:`app.estimator.clarify_policy.NL_PARSE_CLARIFY_POLICY`).

Design notes:

- **Black-box.** Only ``structured_completion`` is used — no logprobs, no
  provider-contract change. Each sample is the same untrusted-analyst parse call,
  schema-validated identically; sampling adds no new trust surface.
- **Cost is ~N× tokens, latency ~flat.** The N samples run in parallel threads
  (the provider transport is a per-call ``urllib`` round-trip with no shared
  client state). Early-stopping keeps easy inputs cheap: when the first window
  of samples is unanimous, no further samples are drawn.
- **Fail closed.** Disagreement can only *lower* the emitted scores, and the
  hybrid weighting guarantees a fully-disagreeing sample set scores below the
  parse gate's calibrated operating threshold no matter how confident the model
  claims to be (see :data:`HYBRID_AGREEMENT_WEIGHT`). A sample set that is
  unanimously non-``parsed`` is exposed as a direct clarify decision
  (:attr:`SelfConsistencySignal.all_non_parsed`), never as a score.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.estimator.parse_prompt import build_parse_prompt
from app.estimator.parse_recovery import recoverable_parse_result_schema
from app.estimator.pipeline import AnsweredClarification
from app.llm.base import ImageInput, Provider
from app.schemas.parse import ParsedCandidate, ParseDisposition, ParseResult

#: Number of parse samples drawn per input. The research grounding this story
#: uses 3–5 samples; 3 is the documented default because the harness
#: (``tests/parse_calibration``) already shows the decision quality bar is met
#: at N=3, and each extra sample costs a full parse call. Tunable, justified
#: against the harness before changing.
SELF_CONSISTENCY_NUM_SAMPLES = 3

#: Size of the first sampling window for early-stopping. The window is drawn in
#: parallel; when it is *unanimous* (pairwise concordance 1.0 — same
#: disposition, same items, same amounts/units) the remaining samples are not
#: drawn. 2 is the smallest window that can attest agreement at all, so easy,
#: unanimous inputs pay one extra sample over today's single parse call while
#: contested inputs pay the full N (Li et al., ICLR 2024 report 34–84% sample
#: reduction for window-unanimity stopping). Tunable against the harness.
SELF_CONSISTENCY_FIRST_WINDOW = 2

#: Weight of the agreement score in the hybrid signal (the verbalized mean gets
#: the complement). 0.6 is chosen for a fail-closed property at the parse
#: gate's calibrated operating threshold
#: (``app.estimator.clarify_policy.NL_PARSE_CLARIFY_POLICY``): a fully
#: disagreeing sample set (agreement 0.0) caps the hybrid at
#: ``0.4 × verbalized ≤ 0.4``, well below the operating point, even when the
#: model verbalizes total confidence — so structural disagreement always
#: clarifies; a unanimous set (agreement 1.0) lifts a timidly-verbalized easy
#: input (e.g. 0.38) to 0.752, so unanimity rescues the over-ask cases.
#: Justified against the FTY-157 harness (see
#: ``tests/fixtures/parse_calibration/self_consistency_summary.json`` and the
#: FTY-159 bake-off, ``calibration_summary.json``).
HYBRID_AGREEMENT_WEIGHT = 0.6

#: Minimum number of samples required before unanimity can be attested — a single
#: sample trivially "agrees" with itself and says nothing about consistency.
_MIN_SAMPLES_FOR_UNANIMITY = 2

#: The user-stated (FTY-279/FTY-280) nutrition facts a matched item pair must also
#: agree on before the parse reads as unanimous. These are the numbers that become
#: rank-1 ``user_text`` evidence, so unstable/contradictory extraction of them must
#: lower concordance rather than be trusted (see :func:`_stated_nutrition_agreement`).
_STATED_NUTRITION_FIELDS = (
    "stated_calories",
    "stated_protein_g",
    "stated_carbs_g",
    "stated_fat_g",
)


@dataclass(frozen=True)
class SelfConsistencySignal:
    """The uncertainty signal computed from N parse samples of one input.

    ``agreement`` is the pure sampling-agreement score and ``hybrid`` combines
    it with the verbalized confidence (the research's best-performing pairing).
    Both are kept so the FTY-157 harness can compare agreement-only against
    hybrid. Scores are confidence-that-this-should-be-estimated, in [0, 1].
    """

    #: The samples the signal was computed over (post early-stop).
    samples: tuple[ParseResult, ...]
    #: Mean pairwise concordance over the samples (see :func:`agreement_score`).
    agreement: float
    #: Mean self-reported confidence over the ``parsed`` samples; 0.0 when no
    #: sample parsed (a non-parsed sample expresses no estimate confidence).
    verbalized_confidence: float
    #: ``HYBRID_AGREEMENT_WEIGHT × agreement + (1-w) × verbalized_confidence``.
    hybrid: float

    @property
    def samples_used(self) -> int:
        return len(self.samples)

    @property
    def unanimous(self) -> bool:
        """Whether every drawn sample fully agreed (concordance 1.0)."""

        return self.agreement == 1.0 and len(self.samples) > 1

    @property
    def all_non_parsed(self) -> bool:
        """Whether no sample returned a ``parsed`` disposition.

        This is the fail-closed direct-decision case: when the model *never*
        commits to a parse across samples, the input clarifies regardless of any
        score — a unanimous set of ``needs_clarification`` replies has agreement
        1.0, which must not read as estimate-confidence.
        """

        return all(sample.disposition is not ParseDisposition.PARSED for sample in self.samples)

    @classmethod
    def from_samples(cls, samples: Sequence[ParseResult]) -> SelfConsistencySignal:
        """Compute the signal over already-drawn samples."""

        if not samples:
            msg = "at least one parse sample is required"
            raise ValueError(msg)
        agreement = agreement_score(samples)
        verbalized = _verbalized_mean(samples)
        return cls(
            samples=tuple(samples),
            agreement=agreement,
            verbalized_confidence=verbalized,
            hybrid=hybrid_score(agreement, verbalized),
        )


def evaluate_self_consistency(
    provider: Provider,
    raw_text: str,
    *,
    answered: Sequence[AnsweredClarification] = (),
    images: Sequence[ImageInput] = (),
    num_samples: int = SELF_CONSISTENCY_NUM_SAMPLES,
    first_window: int = SELF_CONSISTENCY_FIRST_WINDOW,
    max_repair_attempts: int = 0,
) -> SelfConsistencySignal:
    """Sample the parse ``num_samples`` times and compute the consistency signal.

    Samples run in parallel (latency ~flat vs one call); when the first
    ``first_window`` samples are unanimous the rest are skipped (cost guard for
    easy inputs). ``answered`` is forwarded to every sample's prompt (FTY-171),
    and ``images`` — the event's vision evidence surfaces (FTY-376) — to every
    sample's provider call. Any sample failure propagates the
    provider/validation error unchanged — the parse step's existing error
    mapping owns routing it, and a partially-failed sample set is never
    silently scored.
    """

    samples = collect_parse_samples(
        provider,
        raw_text,
        answered=answered,
        images=images,
        num_samples=num_samples,
        first_window=first_window,
        max_repair_attempts=max_repair_attempts,
    )
    return SelfConsistencySignal.from_samples(samples)


def collect_parse_samples(
    provider: Provider,
    raw_text: str,
    *,
    answered: Sequence[AnsweredClarification] = (),
    images: Sequence[ImageInput] = (),
    num_samples: int = SELF_CONSISTENCY_NUM_SAMPLES,
    first_window: int = SELF_CONSISTENCY_FIRST_WINDOW,
    max_repair_attempts: int = 0,
) -> tuple[ParseResult, ...]:
    """Draw parse samples with parallel execution and unanimity early-stopping.

    ``answered`` folds the accumulated clarification answers into every
    sample's prompt as structured detail on an answer-triggered re-estimate
    (FTY-171) — each sample must see the same production prompt, answers
    included, or agreement would be measured against a different parse.
    ``images`` (FTY-376) attaches the event's vision evidence surfaces to every
    sample's provider call, with the matching image-evidence framing in the
    prompt; empty leaves the text-only call byte-for-byte unchanged.

    The stop rule (documented tunable): draw ``min(first_window, num_samples)``
    samples in parallel; if that window is unanimous (agreement exactly 1.0,
    which requires at least two samples to attest), stop; otherwise draw the
    remaining samples in parallel and return all of them. A window of 1 can
    never attest unanimity, so ``first_window=1`` always escalates to the full N.
    """

    if num_samples < 1:
        msg = "num_samples must be >= 1"
        raise ValueError(msg)
    if first_window < 1:
        msg = "first_window must be >= 1"
        raise ValueError(msg)

    prompt = build_parse_prompt(raw_text, answered, image_count=len(images))
    window = min(first_window, num_samples)
    samples = _sample_parallel(
        provider, prompt, window, images=images, max_repair_attempts=max_repair_attempts
    )
    if len(samples) < num_samples and not _is_unanimous(samples):
        samples += _sample_parallel(
            provider,
            prompt,
            num_samples - len(samples),
            images=images,
            max_repair_attempts=max_repair_attempts,
        )
    return samples


def apply_early_stop(
    samples: Sequence[ParseResult],
    *,
    first_window: int = SELF_CONSISTENCY_FIRST_WINDOW,
) -> tuple[ParseResult, ...]:
    """Return the prefix of ``samples`` the live stop rule would have drawn.

    This lets recorded/offline evaluation (the FTY-157 harness fixture carries
    the full N samples per example) score exactly what production would compute:
    a unanimous first window keeps only that window, anything else keeps all
    samples. Mirrors :func:`collect_parse_samples`'s stop rule by construction.
    """

    window = samples[:first_window]
    if len(window) < len(samples) and _is_unanimous(window):
        return tuple(window)
    return tuple(samples)


def agreement_score(samples: Sequence[ParseResult]) -> float:
    """Mean pairwise concordance over all unordered sample pairs, in [0, 1].

    A single sample has no pairs and scores 1.0 by definition (the degenerate
    N=1 configuration reduces the hybrid to the verbalized signal). See
    :func:`pair_concordance` for the pair metric.
    """

    if not samples:
        msg = "at least one parse sample is required"
        raise ValueError(msg)
    if len(samples) == 1:
        return 1.0
    pairs = [
        pair_concordance(samples[i], samples[j])
        for i in range(len(samples))
        for j in range(i + 1, len(samples))
    ]
    return sum(pairs) / len(pairs)


def pair_concordance(a: ParseResult, b: ParseResult) -> float:
    """Concordance between two schema-valid parse samples, in [0, 1].

    The metric (the story's "matched-item fraction × amount-agreement",
    made precise):

    - Different dispositions → 0.0. Disposition disagreement is itself the
      uncertainty being measured; no item credit can offset it.
    - Both ``unparseable`` → 1.0 (they agree the input is not a log).
    - Both item lists empty → 1.0; exactly one empty → 0.0.
    - Otherwise: items are multiset-matched on ``(type, normalised name)``;
      ``matched_fraction = matches / max(|a|, |b|)`` so extra or missing items
      dilute agreement, and the score is ``matched_fraction × mean quantity
      agreement over the matched pairs`` (see :func:`_quantity_agreement`).

    Only schema-validated structure is compared — never raw model text — so the
    metric adds no logging/trace surface for unsanitized output.
    """

    if a.disposition is not b.disposition:
        return 0.0
    if a.disposition is ParseDisposition.UNPARSEABLE:
        return 1.0
    if not a.items and not b.items:
        return 1.0
    if not a.items or not b.items:
        return 0.0

    matched = _match_items(a.items, b.items)
    if not matched:
        return 0.0
    matched_fraction = len(matched) / max(len(a.items), len(b.items))
    quantity = sum(_quantity_agreement(x, y) for x, y in matched) / len(matched)
    return matched_fraction * quantity


def hybrid_score(agreement: float, verbalized: float) -> float:
    """Combine agreement with the verbalized confidence into one score.

    ``w × agreement + (1-w) × verbalized`` with ``w = HYBRID_AGREEMENT_WEIGHT``.
    The weight's fail-closed rationale is documented on the constant.
    """

    return HYBRID_AGREEMENT_WEIGHT * agreement + (1.0 - HYBRID_AGREEMENT_WEIGHT) * verbalized


def _is_unanimous(samples: Sequence[ParseResult]) -> bool:
    """Whether ``samples`` can attest full agreement (needs >= 2 samples)."""

    return len(samples) >= _MIN_SAMPLES_FOR_UNANIMITY and agreement_score(samples) == 1.0


def _sample_parallel(
    provider: Provider,
    prompt: str,
    count: int,
    *,
    images: Sequence[ImageInput],
    max_repair_attempts: int,
) -> tuple[ParseResult, ...]:
    """Draw ``count`` parse samples concurrently and return them in submit order.

    Uses one thread per sample: each sample is an independent blocking provider
    round-trip (per-call transport, no shared client state), so N samples take
    ~one call's latency. The first failed sample's error propagates unchanged;
    the executor's context manager still waits for in-flight siblings.
    """

    if count == 1:
        return (
            _sample_once(provider, prompt, images=images, max_repair_attempts=max_repair_attempts),
        )
    with ThreadPoolExecutor(max_workers=count, thread_name_prefix="parse-sample") as pool:
        futures = [
            pool.submit(
                _sample_once,
                provider,
                prompt,
                images=images,
                max_repair_attempts=max_repair_attempts,
            )
            for _ in range(count)
        ]
        return tuple(future.result() for future in futures)


def _sample_once(
    provider: Provider,
    prompt: str,
    *,
    images: Sequence[ImageInput],
    max_repair_attempts: int,
) -> ParseResult:
    """Draw one structured sample through the public provider contract.

    ``images`` rides the same call for an image-bearing event (FTY-376); an
    empty sequence keeps the text-only call byte-for-byte unchanged.
    """

    schema = recoverable_parse_result_schema(max_repair_attempts)
    if images:
        return provider.structured_completion(prompt, schema, images=list(images))
    return provider.structured_completion(prompt, schema)


def _verbalized_mean(samples: Sequence[ParseResult]) -> float:
    """Mean self-reported confidence over the ``parsed`` samples.

    A non-``parsed`` sample's confidence describes its *own* disposition, not
    confidence in an estimate, so it is excluded; when no sample parsed the
    verbalized component is 0.0 (fail closed — and
    :attr:`SelfConsistencySignal.all_non_parsed` is the operative decision).
    """

    parsed = [s.confidence for s in samples if s.disposition is ParseDisposition.PARSED]
    if not parsed:
        return 0.0
    return sum(parsed) / len(parsed)


def _match_items(
    a: Sequence[ParsedCandidate], b: Sequence[ParsedCandidate]
) -> list[tuple[ParsedCandidate, ParsedCandidate]]:
    """Multiset-match items across two samples on ``(type, normalised name)``.

    Duplicate keys pair off in listed order (deterministic); unmatched items on
    either side simply reduce the matched fraction.
    """

    by_key_b: dict[tuple[str, str], list[ParsedCandidate]] = {}
    for item in b:
        by_key_b.setdefault(_item_key(item), []).append(item)

    counts_b = Counter(_item_key(item) for item in b)
    matched: list[tuple[ParsedCandidate, ParsedCandidate]] = []
    used: Counter[tuple[str, str]] = Counter()
    for item in a:
        key = _item_key(item)
        if used[key] < counts_b.get(key, 0):
            matched.append((item, by_key_b[key][used[key]]))
            used[key] += 1
    return matched


def _item_key(item: ParsedCandidate) -> tuple[str, str]:
    return (item.type.value, _normalise(item.name))


def _quantity_agreement(a: ParsedCandidate, b: ParsedCandidate) -> float:
    """Agreement of two matched items' structured quantities, in [0, 1].

    - Units (normalised): both present and different → 0.0; a missing unit is
      not a contradiction (models often omit it) and is treated as compatible.
    - Amounts: both absent → 1.0 (the samples agree there is no amount);
      exactly one absent → 0.0; both present → ``min/max`` ratio (1.0 when
      equal, both-zero counts as equal).
    - Stated nutrition (FTY-279/FTY-280): folded in as a multiplicative factor so
      unstable/contradictory extraction of a user-stated calorie total or macro
      pulls the pair below unanimity (see :func:`_stated_nutrition_agreement`).

    ``quantity_text`` is deliberately not compared: it is raw phrasing that
    varies harmlessly across samples ("2" vs "two"); the structured
    ``amount``/``unit`` normalisation is the comparable signal.
    """

    unit_a, unit_b = _normalise(a.unit or ""), _normalise(b.unit or "")
    if unit_a and unit_b and unit_a != unit_b:
        return 0.0
    return _amount_agreement(a.amount, b.amount) * _stated_nutrition_agreement(a, b)


def _amount_agreement(amount_a: float | None, amount_b: float | None) -> float:
    """Agreement of two matched items' structured amounts, in [0, 1]."""

    if amount_a is None and amount_b is None:
        return 1.0
    if amount_a is None or amount_b is None:
        return 0.0
    if amount_a == amount_b:
        return 1.0
    low, high = sorted((amount_a, amount_b))
    # ``high > 0`` always holds here (amounts are >= 0 and unequal), but guard
    # anyway so the ratio can never divide by zero.
    return low / high if high > 0 else 0.0


def _stated_nutrition_agreement(a: ParsedCandidate, b: ParsedCandidate) -> float:
    """Agreement over the user-stated nutrition facts of two matched items, in [0, 1].

    Only fields *in play* — those at least one sample extracted — are scored, so an
    ordinary parse that states no nutrition is unaffected (1.0), keeping the metric
    identical for the non-user-text path. For a scored field:

    - both present → ``min/max`` ratio (a contradictory calorie total across samples
      scores low, so it cannot read as unanimous);
    - exactly one present → 0.0 (the samples disagree on whether the user stated the
      fact at all — an unstable extraction, not agreement).

    This is the trust gate for the rank-1 ``user_text`` tier: a stated calorie total
    is persisted as user-stated evidence only when the samples agree it was stated
    *and* agree on the value (``docs/contracts/parse-candidates.md``).
    """

    scores = [
        _ratio(getattr(a, field), getattr(b, field))
        for field in _STATED_NUTRITION_FIELDS
        if getattr(a, field) is not None or getattr(b, field) is not None
    ]
    if not scores:
        return 1.0
    return sum(scores) / len(scores)


def _ratio(x: float | None, y: float | None) -> float:
    """``min/max`` agreement of two stated facts, in [0, 1].

    Both present and equal → 1.0 (both-zero included); exactly one present → 0.0
    (the samples disagree on whether the fact was stated). Stated facts are schema-
    bounded non-negative, so the ratio is well-defined.
    """

    if x == y:
        return 1.0
    if x is None or y is None:
        return 0.0
    low, high = sorted((x, y))
    return low / high if high > 0 else 0.0


def _normalise(text: str) -> str:
    """Casefold and collapse whitespace so trivial phrasing differences match."""

    return " ".join(text.casefold().split())

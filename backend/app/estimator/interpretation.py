"""The interpretation session — the model owns the hypothesis (FTY-325).

Implements the interpreter core of the FTY-324 ``InterpretationSession``
contract (``docs/contracts/parse-candidates.md``, v9): one run-local session
owns the model's understanding of a natural-language log for the lifetime of
the estimation run. The initial parse is the session's *first hypothesis*, not
the pipeline's frozen truth — the session keeps the raw text (plus answered
clarifications) in scope for every model interpretation call, and revises the
item hypothesis when the evidence demands it.

The concrete failure class this makes structurally impossible to freeze: a
two-item branded phrase whose parse samples disagree (one sample reads both
items, others collapse to a single generic, brandless, amountless candidate)
must not silently aggregate into the degenerate candidate. Structural
disagreement across samples — on item count, identity, or brand — triggers a
bounded **re-interpretation** call instead: the model re-reads the raw entry
and produces its single best complete interpretation, which becomes the
revised hypothesis.

Division of authority (unchanged from FTY-324):

- the **model** owns interpretation — which items the entry describes, their
  identities, brands, and amounts;
- **deterministic code** owns schema validation, the calibrated agreement
  signal (ADR 0003 — computed over the original sample set and never replaced
  by a self-reported score), the plausibility/identity/stated-nutrition gates
  (validators over the hypothesis, in ``parse.py``), math, provenance,
  privacy, and persistence.

Trust and privacy boundary: raw diary text lives only in memory on this
session (and in the user-owned ``log_events.raw_text`` row). Provider calls
may include it — unchanged from today's parse — but everything recorded onto
the run trace goes through :mod:`app.estimator.decision_trace` sanitizers and
carries only counts, kinds, and revision-reason labels
(``decision = hypothesis_revision``, outcome vocabulary pinned in
``parse-candidates.md``). Re-interpretation calls are capped per session so a
pathological phrase cannot loop unbounded.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.enums import CandidateType
from app.estimator.decision_trace import (
    amount_kind,
    sanitize_trace_label,
    sanitize_trace_source_ref,
)
from app.estimator.parse_prompt import build_reinterpretation_prompt
from app.estimator.parse_recovery import recoverable_parse_result_schema
from app.estimator.pipeline import (
    AnsweredClarification,
    ClarificationDraft,
    EstimationContext,
    StepError,
    StepFailed,
)
from app.estimator.self_consistency import (
    SelfConsistencySignal,
    collect_parse_samples,
)
from app.llm.errors import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTransientError,
    StructuredOutputValidationError,
)
from app.schemas.parse import ParsedCandidate, ParseDisposition, ParseResult

if TYPE_CHECKING:
    from app.estimator.parse_policy import ParsePolicySettings
    from app.llm.base import Provider

__all__ = [
    "MAX_HYPOTHESIS_REVISION_CALLS",
    "EvidenceRecord",
    "HypothesisItem",
    "InterpretationHypothesis",
    "InterpretationSession",
    "ItemLink",
    "PolicyView",
    "hypothesis_samples_disagree",
    "representative_sample",
]

#: Per-session cap on model re-interpretation calls (documented tunable). The
#: initial N-sample parse already bounds provider cost; each re-interpretation
#: is one additional parse-class call, so the session budget keeps a
#: pathological phrase at N+cap calls total. FTY-326's evidence-driven
#: re-interpretation shares this same counter — the cap is per *session*, not
#: per trigger — and may revisit the value with its own cost data.
MAX_HYPOTHESIS_REVISION_CALLS = 1

#: Minimum item-bearing samples required to attest structural disagreement — a
#: single item-bearing sample has nothing to disagree with. Also the smallest
#: "many" side of a split/merge (one item into at least two, or vice versa).
_MIN_ITEMS_FOR_STRUCTURE = 2


@dataclass(frozen=True)
class HypothesisItem:
    """One item of the current hypothesis, with its run-local identity.

    ``hypothesis_item_id`` is stable across revisions for items the model kept
    (matched on kind + normalised name); it exists only inside the estimation
    run and is never exposed as user data.
    """

    hypothesis_item_id: int
    candidate: ParsedCandidate


@dataclass(frozen=True)
class ItemLink:
    """Run-local split/merge lineage between hypothesis items (traceability only)."""

    source_item_id: int
    revised_item_id: int


@dataclass(frozen=True)
class InterpretationHypothesis:
    """The session's current working hypothesis over the log's items.

    A run-local working object per FTY-324: not a public DTO, never persisted
    wholesale. ``revision`` starts at 0 for the initial interpretation and
    increments once per applied revision.
    """

    revision: int
    items: tuple[HypothesisItem, ...]
    item_links: tuple[ItemLink, ...] = ()


@dataclass(frozen=True)
class EvidenceRecord:
    """One bounded evidence-ledger entry: sanitized labels and refs only.

    Per the FTY-324 ``evidence_view`` contract this never carries raw fetched
    pages, snippets, provider output, or search queries — the fields are the
    same content-free vocabulary the decision trace uses.
    """

    tier: str
    outcome: str
    source_ref: str | None = None

    def as_label(self) -> str:
        """Render the record as one sanitized evidence-status prompt line.

        Provider calls may carry raw diary text but nothing else raw (FTY-325
        security requirement), so every field passes through the decision-trace
        sanitizers here — at the egress seam — rather than trusting the caller:
        a ``source_ref`` embedding a URL keeps only scheme/host/path with
        secret-looking material redacted, and labels are bounded and redacted.
        """

        base = f"{sanitize_trace_label(self.tier)}: {sanitize_trace_label(self.outcome)}"
        if self.source_ref is None:
            return base
        ref = sanitize_trace_source_ref(self.source_ref)
        return f"{base} ({ref})" if ref else base


@dataclass(frozen=True)
class PolicyView:
    """Active clarify mode plus the calibrated signal metadata (FTY-324)."""

    mode: str
    agreement: float
    verbalized_confidence: float
    hybrid: float
    samples_used: int


def representative_sample(samples: Sequence[ParseResult]) -> ParseResult:
    """The sample whose candidates seed the hypothesis when the set is trusted.

    Preference order: the most self-confident ``parsed`` sample (every parsed
    sample is an equally schema-valid parse; the verbalized score is the only
    within-set ranking the model expresses), then — for non-parsed sets that may
    still estimate via the FTY-167 detail override — the most confident sample
    that extracted items, then the first sample. ``max`` keeps the earliest of
    equally-confident samples, so the choice is deterministic for a recorded
    sample set.
    """

    parsed = [s for s in samples if s.disposition is ParseDisposition.PARSED]
    pool = parsed or [s for s in samples if s.items] or list(samples)
    return max(pool, key=lambda sample: sample.confidence)


def hypothesis_samples_disagree(samples: Sequence[ParseResult]) -> bool:
    """Whether the sample set structurally disagrees on item count/identity/brand.

    This is the FTY-325 re-interpretation trigger. Only samples that extracted
    at least one item can attest disagreement about the item set (a no-item
    ``needs_clarification`` sample expresses "can't parse", not "zero items"),
    and at least two such samples are required. Amount/unit/stated-nutrition
    jitter deliberately does *not* trigger — quantity disagreement is the
    calibrated agreement signal's concern (ADR 0003), not a degenerate item
    set; re-asking for it would spend provider budget on ordinary sampling
    noise.
    """

    bearing = [sample for sample in samples if sample.items]
    if len(bearing) < _MIN_ITEMS_FOR_STRUCTURE:
        return False
    profiles = {tuple(sorted(_item_profile(item) for item in sample.items)) for sample in bearing}
    return len(profiles) > 1


def _item_profile(item: ParsedCandidate) -> tuple[str, str, str]:
    """The structural identity a sample asserts for one item: kind, name, brand."""

    return (item.type.value, _normalise(item.name), _normalise(item.brand or ""))


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


class InterpretationSession:
    """Owns the model's interpretation of one log event for the run's lifetime.

    Created by the parse step, carried on the
    :class:`~app.estimator.pipeline.EstimationContext` so later steps (FTY-326)
    can consult and re-open interpretation. Holds the raw text in memory only —
    the session itself is never persisted, and everything it records onto the
    run trace is sanitized labels.
    """

    def __init__(
        self,
        provider: Provider,
        raw_text: str,
        *,
        policy: ParsePolicySettings,
        answered: Sequence[AnsweredClarification] = (),
        step_name: str = "parse",
        max_revision_calls: int = MAX_HYPOTHESIS_REVISION_CALLS,
    ) -> None:
        self._provider = provider
        self._policy = policy
        self._step_name = step_name
        self._max_revision_calls = max_revision_calls
        self._revision_calls_used = 0
        self._next_item_id = 0
        #: Run-local identifier (FTY-324); never exposed as user data.
        self.session_id = uuid.uuid4().hex
        #: The owning event's raw text — available to the configured LLM
        #: provider only, never copied into trace/assumptions/refs/errors.
        self.raw_text = raw_text
        self.clarification_answers = tuple(answered)
        self.evidence_ledger: list[EvidenceRecord] = []
        self.pending_questions: tuple[ClarificationDraft, ...] = ()
        self.signal: SelfConsistencySignal | None = None
        self.hypothesis: InterpretationHypothesis | None = None
        self._result: ParseResult | None = None

    @property
    def result(self) -> ParseResult:
        """The current hypothesis as a schema-validated ``ParseResult``."""

        if self._result is None:
            msg = "interpret_initial has not run"
            raise RuntimeError(msg)
        return self._result

    @property
    def policy_view(self) -> PolicyView:
        """Active mode plus calibrated signal metadata (FTY-324 ``policy_view``)."""

        if self.signal is None:
            msg = "interpret_initial has not run"
            raise RuntimeError(msg)
        return PolicyView(
            mode=self._policy.mode,
            agreement=self.signal.agreement,
            verbalized_confidence=self.signal.verbalized_confidence,
            hybrid=self.signal.hybrid,
            samples_used=self.signal.samples_used,
        )

    def interpret_initial(self, context: EstimationContext) -> SelfConsistencySignal:
        """Form the initial hypothesis from the FTY-158 sample set.

        Draws the N parse samples (parallel, unanimity early stop — machinery
        unchanged), computes the calibrated agreement signal over them, and
        seeds the hypothesis from the representative sample. When the samples
        structurally disagree on item count/identity/brand, the session
        re-interprets instead of freezing the aggregate: one bounded provider
        re-ask whose validated reply becomes the revised hypothesis, with the
        revision recorded under sanitized trace labels.
        """

        samples = self._collect_samples()
        signal = SelfConsistencySignal.from_samples(samples)
        self.signal = signal
        initial = representative_sample(samples)
        self._result = initial
        self.hypothesis = InterpretationHypothesis(revision=0, items=self._new_items(initial.items))
        self._record_snapshot(context, outcome="initial_hypothesis")
        if hypothesis_samples_disagree(samples):
            self._revise_from_model(context)
        return signal

    def reinterpret(self, context: EstimationContext) -> ParseResult | None:
        """Re-open interpretation with the raw text plus accumulated evidence.

        The FTY-326 seam: later steps call this when gathered evidence implies
        the current hypothesis is degenerate, over/under-split, or mis-keyed.
        Shares the session's revision-call budget; returns the revised result,
        or ``None`` when the budget is exhausted (recorded as
        ``revision_truncated`` — the current hypothesis stands).
        """

        return self._revise_from_model(context)

    def adopt_result(self, context: EstimationContext, result: ParseResult) -> None:
        """Adopt a routing-selected schema-valid result as the hypothesis.

        Deterministic policy routing may settle on a different validated sample
        than the session's current pick (the FTY-167/FTY-298 recognizable-
        identity fallback). The session stays the single owner of the working
        hypothesis, so the replacement is applied — and traced — as an ordinary
        revision.
        """

        if result is not self._result:
            self._apply_revision(context, result)

    def add_evidence(self, record: EvidenceRecord) -> None:
        """Append one sanitized evidence record to the session ledger (FTY-326)."""

        self.evidence_ledger.append(record)

    def note_pending_questions(
        self,
        context: EstimationContext,
        questions: Sequence[ClarificationDraft],
        *,
        outcome: str,
    ) -> None:
        """Record that the run is stopping on questions (validator or policy).

        ``outcome`` is ``deterministic_gate_failed`` for a validator stop and
        ``clarification_needed`` for a policy clarify decision — sanitized
        labels only; the question text itself is persisted as product data by
        the worker, never copied into the trace.
        """

        self.pending_questions = tuple(questions)
        context.record_decision(self._step_name, "hypothesis_revision", outcome=outcome)

    def _collect_samples(self) -> tuple[ParseResult, ...]:
        """Draw the sample set, mapping provider failures to step signals.

        Transient transport failures are retryable (:class:`StepError`); a
        schema-validation rejection or any other deterministic provider error
        is terminal and fails closed (:class:`StepFailed`) — a partially-failed
        sample set is never scored, and rejected output is never trusted.
        """

        try:
            return collect_parse_samples(
                self._provider,
                self.raw_text,
                answered=self.clarification_answers,
                max_repair_attempts=self._policy.max_repair_attempts,
            )
        except StructuredOutputValidationError as exc:
            raise StepFailed("schema_validation_failed") from exc
        except LLMTransientError as exc:
            raise StepError("provider_transient_error") from exc
        except (LLMResponseError, LLMConfigurationError) as exc:
            raise StepFailed("provider_error") from exc

    def _revise_from_model(self, context: EstimationContext) -> ParseResult | None:
        """One budget-capped re-interpretation call; applies the revision.

        Per the FTY-324 decision-point shape the re-ask passes the raw text,
        answered clarifications, the *current hypothesis*, and the evidence
        view back to the model — the model must see the item set and fields it
        is revising, not just the inputs that produced them.
        """

        hypothesis = self.hypothesis
        if hypothesis is None:
            msg = "interpret_initial has not run"
            raise RuntimeError(msg)
        if self._revision_calls_used >= self._max_revision_calls:
            context.record_decision(
                self._step_name, "hypothesis_revision", outcome="revision_truncated"
            )
            return None
        self._revision_calls_used += 1
        prompt = build_reinterpretation_prompt(
            self.raw_text,
            self.clarification_answers,
            hypothesis_items=[item.candidate for item in hypothesis.items],
            evidence_labels=[record.as_label() for record in self.evidence_ledger],
        )
        schema = recoverable_parse_result_schema(self._policy.max_repair_attempts)
        try:
            revised = self._provider.structured_completion(prompt, schema)
        except StructuredOutputValidationError as exc:
            # Untrusted-analyst boundary, unchanged: a re-ask reply is validated
            # exactly like a sample, and invalid output fails the run closed
            # rather than being partially trusted.
            raise StepFailed("schema_validation_failed") from exc
        except LLMTransientError as exc:
            raise StepError("provider_transient_error") from exc
        except (LLMResponseError, LLMConfigurationError) as exc:
            raise StepFailed("provider_error") from exc
        self._apply_revision(context, revised)
        return self._result

    def _apply_revision(self, context: EstimationContext, revised: ParseResult) -> None:
        """Diff the current hypothesis against ``revised`` and adopt it.

        Matched items (kind + normalised name, multiset order) keep their
        run-local ids; each structural change is traced with its sanitized
        revision label. A one-into-many replacement is a split, many-into-one a
        merge — both recorded with coarse item links for lineage.
        """

        hypothesis = self.hypothesis
        if hypothesis is None:
            msg = "interpret_initial has not run"
            raise RuntimeError(msg)
        old_items = list(self.result.items)
        new_items = list(revised.items)
        matched = _match_indices(old_items, new_items)
        matched_old = {old_i for old_i, _ in matched}
        matched_new = {new_i for _, new_i in matched}
        removed = [i for i in range(len(old_items)) if i not in matched_old]
        added = [j for j in range(len(new_items)) if j not in matched_new]

        field_events = [
            (outcome, new_i)
            for old_i, new_i in matched
            for outcome in _field_revisions(old_items[old_i], new_items[new_i])
        ]
        if not removed and not added and not field_events:
            # The re-read agreed with the current hypothesis: keep it, and say so.
            context.record_decision(
                self._step_name,
                "hypothesis_revision",
                outcome="hypothesis_kept",
                result_count=len(new_items),
            )
            return

        split = len(removed) == 1 and len(added) >= _MIN_ITEMS_FOR_STRUCTURE
        merged = len(removed) >= _MIN_ITEMS_FOR_STRUCTURE and len(added) == 1
        self._record_revision_events(
            context, old_items, new_items, removed, added, field_events, split=split, merged=merged
        )
        self.hypothesis = self._revised_hypothesis(
            hypothesis, new_items, matched, removed, added, split=split, merged=merged
        )
        self._result = revised

    def _record_revision_events(
        self,
        context: EstimationContext,
        old_items: Sequence[ParsedCandidate],
        new_items: Sequence[ParsedCandidate],
        removed: Sequence[int],
        added: Sequence[int],
        field_events: Sequence[tuple[str, int]],
        *,
        split: bool,
        merged: bool,
    ) -> None:
        """Trace each structural change under its sanitized revision label."""

        count = len(new_items)
        removed_outcome = "item_split" if split else "item_removed"
        for old_i in removed:
            self._record_item(
                context, old_items[old_i], outcome=removed_outcome, index=old_i, count=count
            )
        added_outcome = "item_merged" if merged else "item_added"
        for new_i in added:
            self._record_item(
                context, new_items[new_i], outcome=added_outcome, index=new_i, count=count
            )
        for outcome, new_i in field_events:
            self._record_item(context, new_items[new_i], outcome=outcome, index=new_i, count=count)

    def _revised_hypothesis(
        self,
        hypothesis: InterpretationHypothesis,
        new_items: Sequence[ParsedCandidate],
        matched: Sequence[tuple[int, int]],
        removed: Sequence[int],
        added: Sequence[int],
        *,
        split: bool,
        merged: bool,
    ) -> InterpretationHypothesis:
        """Rebuild the hypothesis: matched items keep ids; splits/merges link lineage."""

        id_by_new_index: dict[int, int] = {}
        for old_i, new_i in matched:
            id_by_new_index[new_i] = hypothesis.items[old_i].hypothesis_item_id
        for new_i in added:
            id_by_new_index[new_i] = self._allocate_item_id()
        items = tuple(
            HypothesisItem(hypothesis_item_id=id_by_new_index[i], candidate=item)
            for i, item in enumerate(new_items)
        )
        links = list(hypothesis.item_links)
        if split:
            source = hypothesis.items[removed[0]].hypothesis_item_id
            links.extend(ItemLink(source, id_by_new_index[j]) for j in added)
        elif merged:
            target = id_by_new_index[added[0]]
            links.extend(ItemLink(hypothesis.items[i].hypothesis_item_id, target) for i in removed)
        return InterpretationHypothesis(
            revision=hypothesis.revision + 1, items=items, item_links=tuple(links)
        )

    def _record_snapshot(self, context: EstimationContext, *, outcome: str) -> None:
        """Trace the current hypothesis: candidate count + per-candidate labels."""

        items = list(self.result.items)
        context.record_decision(
            self._step_name, "hypothesis_revision", outcome=outcome, result_count=len(items)
        )
        for index, item in enumerate(items):
            self._record_item(context, item, outcome=outcome, index=index, count=len(items))

    def _record_item(
        self,
        context: EstimationContext,
        item: ParsedCandidate,
        *,
        outcome: str,
        index: int,
        count: int,
    ) -> None:
        """One sanitized per-candidate trace entry — labels only, never text."""

        context.record_decision(
            self._step_name,
            "hypothesis_revision",
            outcome=outcome,
            candidate_index=index,
            # The parse contract keeps generic brands empty ("" is schema-valid),
            # so only a non-blank brand counts as branded in the trace.
            has_brand=bool(item.brand and item.brand.strip()),
            amount_kind=amount_kind(item.unit, item.amount, item.quantity_text),
            result_count=count,
        )

    def _new_items(self, items: Sequence[ParsedCandidate]) -> tuple[HypothesisItem, ...]:
        return tuple(
            HypothesisItem(hypothesis_item_id=self._allocate_item_id(), candidate=item)
            for item in items
        )

    def _allocate_item_id(self) -> int:
        self._next_item_id += 1
        return self._next_item_id


def _match_indices(
    old_items: Sequence[ParsedCandidate], new_items: Sequence[ParsedCandidate]
) -> list[tuple[int, int]]:
    """Multiset-match item indexes across revisions on kind + normalised name."""

    unused_new: dict[tuple[str, str], list[int]] = {}
    for index, item in enumerate(new_items):
        unused_new.setdefault(_match_key(item), []).append(index)
    matched: list[tuple[int, int]] = []
    for index, item in enumerate(old_items):
        pool = unused_new.get(_match_key(item))
        if pool:
            matched.append((index, pool.pop(0)))
    return matched


def _match_key(item: ParsedCandidate) -> tuple[str, str]:
    return (item.type.value, _normalise(item.name))


def _field_revisions(old: ParsedCandidate, new: ParsedCandidate) -> list[str]:
    """Sanitized revision labels for a matched item whose fields changed."""

    events: list[str] = []
    if _normalise(old.brand or "") != _normalise(new.brand or ""):
        events.append("brand_revised")
    quantity_changed = old.amount != new.amount
    unit_changed = _normalise(old.unit or "") != _normalise(new.unit or "")
    if old.type is CandidateType.EXERCISE:
        if quantity_changed or unit_changed:
            events.append("exercise_detail_revised")
    else:
        if quantity_changed:
            events.append("quantity_revised")
        if unit_changed:
            events.append("unit_revised")
    if any(
        getattr(old, field_name) != getattr(new, field_name)
        for field_name in (
            "stated_calories",
            "stated_protein_g",
            "stated_carbs_g",
            "stated_fat_g",
        )
    ):
        events.append("stated_nutrition_revised")
    return events

"""Adapters that let evidence tiers consult the interpretation session (FTY-326).

The session owns the model's revisable hypothesis, while deterministic resolver
steps own source gates, math, budgets, and persistence.  This module is the
small bridge between those worlds: tiers can record sanitized evidence labels on
the session ledger, read the current food hypothesis as ordinary
``CandidateDraft`` values, and spend the session's one bounded evidence-driven
re-interpretation pass before falling to model-prior.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from app.enums import CandidateType
from app.estimator.decision_trace import MAX_TRACE_DESC_LEN, sanitize_trace_label
from app.estimator.fdc import ProductFacts
from app.estimator.interpretation import EvidenceRecord, InterpretationSession
from app.estimator.pipeline import CandidateDraft, EstimationContext, StepError, StepFailed
from app.estimator.searched_reference import StageEvidenceText
from app.schemas.parse import ParsedCandidate

INTERPRETATION_TIER = "interpretation_session"

#: Tokenizer for the staged-excerpt echo filter (matches the session's own).
_TAINT_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


def add_evidence_record(  # noqa: PLR0913 - mirrors the bounded evidence-view field set.
    context: EstimationContext,
    *,
    tier: str,
    outcome: object,
    source_ref: object | None = None,
    decision: object | None = None,
    query_variant: object | None = None,
    search_status: object | None = None,
    result_count: object | None = None,
    source_desc: object | None = None,
    surface: object | None = None,
) -> None:
    """Append a bounded, sanitized evidence record to the session ledger.

    The ``EvidenceRecord`` renders through the decision-trace sanitizers at the
    provider-egress seam, so callers may pass the same bounded labels/source refs
    they already send to ``record_decision``.  ``source_desc`` is for a bounded
    source-stated identity descriptor (for example, a global database description)
    when the session needs the evidence surface that a compatibility/serving
    decision saw. Raw page/snippet/query/user text must never be passed here, and
    a provider-transcribed identity (page/snippet extraction ``product_name``)
    must be reduced through
    :func:`~app.estimator.identity_sanitizer.sanitized_identity` by the caller
    first — the trace sanitizers bound and redact secrets but do not sanitize
    open-vocabulary identity text.
    """

    session = context.interpretation_session
    if session is None or outcome is None:
        return
    session.add_evidence(
        EvidenceRecord(
            tier=str(tier),
            outcome=str(outcome),
            source_ref=None if source_ref is None else str(source_ref),
            decision=None if decision is None else str(decision),
            query_variant=_coerce_evidence_count(query_variant),
            search_status=None if search_status is None else str(search_status),
            result_count=_coerce_evidence_count(result_count),
            source_desc=None if source_desc is None else str(source_desc),
            surface=None if surface is None else str(surface),
        )
    )


def evidence_text_stager(context: EstimationContext, *, tier: str) -> StageEvidenceText:
    """A tier-bound seam staging unaccepted-read page/snippet text on the session.

    The transient model-facing half of the FTY-326 evidence split: the staged
    text is bounded and FTY-314-framed by the session and reaches only its next
    re-interpretation prompt — never the evidence ledger, run trace, persisted
    rows, search queries, or fetch URLs, which keep the sanitized label
    representation of the same read. A no-op without a session.
    """

    def _stage(*, surface: object, outcome: object, text: object) -> None:
        session = context.interpretation_session
        if session is None or not isinstance(text, str):
            return
        session.stage_evidence_text(
            tier=tier, surface=str(surface), outcome=str(outcome), text=text
        )

    return _stage


def current_food_candidate(
    context: EstimationContext,
    candidate: CandidateDraft,
    candidate_index: int | None,
) -> CandidateDraft:
    """Return the session's current food draft for ``candidate_index`` if present."""

    drafts = _session_food_drafts(context)
    # Drafts are frozen value objects, so duplicate parsed candidates compare
    # equal and a value scan can hand back the wrong duplicate's (unrevised)
    # draft. The position is the authoritative key — but food candidates may
    # have been claimed/removed by an earlier tier such as user_text, so index
    # is safe only while the session/context food lists still have the same
    # shape.
    if (
        len(drafts) == len(context.food_candidates)
        and candidate_index is not None
        and 0 <= candidate_index < len(drafts)
    ):
        draft = drafts[candidate_index]
        # An identity that was wholly evidence-derived filters to nothing
        # (staged-echo taint); the resolver's known-good value stands instead.
        return draft if draft.name.strip() else candidate
    for draft in drafts:
        if draft == candidate:
            return draft
    for draft in drafts:
        if _same_food_identity(draft, candidate):
            return draft
    return candidate


def evidence_status_labels(context: EstimationContext) -> tuple[str, ...]:
    """Sanitized evidence-ledger labels for provider prompts."""

    session = context.interpretation_session
    if session is None:
        return ()
    return tuple(record.as_label() for record in session.evidence_ledger)


def reinterpret_food_candidate(
    context: EstimationContext,
    candidate: CandidateDraft,
    candidate_index: int | None,
    *,
    step_name: str,
    trigger_tier: str,
) -> CandidateDraft | None:
    """Spend the session's bounded re-interpretation pass and return a revised draft.

    Evidence-tier re-interpretation is advisory to the resolver: if the session has
    no budget, the provider fails, or the model keeps the same food hypothesis, the
    caller continues to model-prior with the current candidate.  When a revised food
    candidate is returned, this helper updates ``context.food_candidates`` at the
    same food index so downstream trace attribution and persistence use the revised
    hypothesis.
    """

    session = context.interpretation_session
    if session is None:
        return None

    try:
        result = session.reinterpret(context)
    except (StepError, StepFailed) as exc:
        outcome = f"requery_{_step_signal_reason(exc)}"
        _record_requery_decision(
            context,
            step_name=step_name,
            candidate_index=candidate_index,
            outcome=outcome,
            trigger_tier=trigger_tier,
        )
        return None

    if result is None:
        _record_requery_decision(
            context,
            step_name=step_name,
            candidate_index=candidate_index,
            outcome="requery_truncated",
            trigger_tier=trigger_tier,
        )
        return None

    revised = current_food_candidate(context, candidate, candidate_index)
    if revised == candidate:
        _record_requery_decision(
            context,
            step_name=step_name,
            candidate_index=candidate_index,
            outcome="requery_identity_unchanged",
            trigger_tier=trigger_tier,
        )
        return None

    if candidate_index is not None and 0 <= candidate_index < len(context.food_candidates):
        context.food_candidates[candidate_index] = revised

    _record_requery_decision(
        context,
        step_name=step_name,
        candidate_index=candidate_index,
        outcome="requery_revised_identity",
        trigger_tier=trigger_tier,
    )
    return revised


def _record_requery_decision(
    context: EstimationContext,
    *,
    step_name: str,
    candidate_index: int | None,
    outcome: str,
    trigger_tier: str,
) -> None:
    context.record_decision(
        step_name,
        "source",
        candidate_index=candidate_index,
        tier=INTERPRETATION_TIER,
        outcome=outcome,
    )
    add_evidence_record(
        context,
        tier=INTERPRETATION_TIER,
        outcome=outcome,
        source_ref=trigger_tier,
    )


def _session_food_drafts(context: EstimationContext) -> tuple[CandidateDraft, ...]:
    session = context.interpretation_session
    if session is None:
        return ()
    try:
        items = session.result.items
    except RuntimeError:
        return ()
    taint = session.evidence_echo_taint() - _descriptor_authorized_tokens(session)
    return tuple(_to_draft(item, taint) for item in items if item.type is CandidateType.FOOD)


def _descriptor_authorized_tokens(session: InterpretationSession) -> frozenset[str]:
    """Tokens a sanitized ledger descriptor stated — source-supported, not an echo.

    The FTY-326 companion rule to the staged-excerpt taint: real page/snippet
    text commonly contains exactly the identity words a legitimate revision
    needs (``PC dill hummus`` → ``Presidents Choice Dill Pickle Hummus``), so a
    token also stated through the ledger's sanitized ``source_desc`` channel — a
    trusted database row description, or an extraction identity already reduced
    through ``sanitized_identity`` — authorizes the revised identity word that
    carries it. Descriptors are tokenized through the same egress sanitizer
    :meth:`EvidenceRecord.as_label` renders with, so material redaction keeps
    out of the model-facing prompt cannot authorize its own excerpt echo.
    """

    tokens: set[str] = set()
    for record in session.evidence_ledger:
        if record.source_desc:
            desc = sanitize_trace_label(record.source_desc, max_len=MAX_TRACE_DESC_LEN)
            tokens.update(_TAINT_TOKEN_RE.findall(desc.lower()))
    return frozenset(tokens)


def _to_draft(item: ParsedCandidate, taint: frozenset[str]) -> CandidateDraft:
    """The resolver-facing view of one hypothesis item, echo-filtered (FTY-326).

    The session's hypothesis may legitimately absorb staged evidence text, but
    the resolver-side identity fields drive search queries, fetch-scoped
    lookups, and persisted item names — surfaces raw page/snippet text must
    never reach. Words carrying a staged-excerpt token that neither the user's
    own words nor a sanitized ledger ``source_desc`` descriptor authorized are
    dropped here, at the one bridge every tier reads through — so a
    source-backed identity revision survives while an unvetted excerpt echo
    does not (:func:`_descriptor_authorized_tokens`). ``quantity_text``
    keeps digit-bearing words (a page-echoed number cannot name a product, and
    its egress path already drops digit tokens) so serving detail survives;
    ``barcode`` is strict — a barcode must be user-supplied, so a page-echoed
    one is dropped whole before it could key an OFF lookup.
    """

    barcode = item.barcode
    if barcode is not None:
        barcode = _drop_tainted_words(barcode, taint) or None
    return CandidateDraft(
        name=_drop_tainted_words(item.name, taint),
        quantity_text=_drop_tainted_words(item.quantity_text, taint, keep_digit_words=True),
        unit=item.unit,
        amount=item.amount,
        barcode=barcode,
        brand=None if item.brand is None else _drop_tainted_words(item.brand, taint),
        stated_calories=item.stated_calories,
        stated_protein_g=item.stated_protein_g,
        stated_carbs_g=item.stated_carbs_g,
        stated_fat_g=item.stated_fat_g,
    )


def _drop_tainted_words(text: str, taint: frozenset[str], *, keep_digit_words: bool = False) -> str:
    """Drop whitespace words carrying an evidence-only token; else return ``text``."""

    if not taint or not text:
        return text
    kept = [word for word in text.split() if not _word_tainted(word, taint, keep_digit_words)]
    return text if len(kept) == len(text.split()) else " ".join(kept)


def _word_tainted(word: str, taint: frozenset[str], keep_digit_words: bool) -> bool:
    tokens = _TAINT_TOKEN_RE.findall(word.lower())
    if keep_digit_words and tokens and all(token.isdigit() for token in tokens):
        return False
    return any(token in taint for token in tokens)


def consult_rejected_rows(
    context: EstimationContext,
    candidate: CandidateDraft,
    candidate_index: int | None,
    *,
    rejected: Sequence[ProductFacts],
    step_name: str,
    tier: str,
) -> CandidateDraft | None:
    """Feed compatibility-rejected source rows to the session and re-ask once.

    The FTY-326 row-acceptance decision point for a trusted-database tier:
    deterministic ranking only *bounds* the option set, so each energy-bearing
    row it turned away is recorded on the ledger (sanitized outcome plus the
    global row description — no user data) and the session may spend its one
    bounded re-interpretation pass on them. Returns the revised draft for the
    caller's single bounded retry, or ``None`` when the session keeps the
    hypothesis — the rejection then stands as a deliberate miss.
    """

    for row in rejected:
        context.record_decision(
            step_name,
            "source",
            candidate_index=candidate_index,
            tier=tier,
            source_ref=row.source_ref,
            source_desc=row.description,
            outcome="rejected_incompatible_row",
        )
        add_evidence_record(
            context,
            tier=tier,
            outcome="rejected_incompatible_row",
            source_ref=row.source_ref,
            source_desc=row.description,
        )
    return reinterpret_food_candidate(
        context, candidate, candidate_index, step_name=step_name, trigger_tier=tier
    )


def _same_food_identity(left: CandidateDraft, right: CandidateDraft) -> bool:
    return _normalise(left.name) == _normalise(right.name)


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def _step_signal_reason(exc: StepError | StepFailed) -> str:
    if isinstance(exc, StepFailed):
        return exc.reason
    return exc.message


def _coerce_evidence_count(value: object | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None

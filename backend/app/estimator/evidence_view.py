"""The interpretation session's evidence-view record + rendering (FTY-354 extraction).

The evidence-ledger entry and its sanitized prompt rendering, carved out of the
:class:`~app.estimator.interpretation.InterpretationSession` (FTY-324
``evidence_view`` contract). The session owns the ledger list and the state
machine; this module owns the record shape and how one record renders to a
single sanitized prompt line. Behaviour is byte-identical to the pre-FTY-354
inline version — every field still passes through the decision-trace sanitizers
at the egress seam.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.estimator.decision_trace import (
    MAX_TRACE_DESC_LEN,
    sanitize_trace_label,
    sanitize_trace_source_ref,
)

# Mirrors the decision-trace count bound without importing its private constant.
_MAX_EVIDENCE_COUNT = 9_999


@dataclass(frozen=True)
class EvidenceRecord:
    """One bounded evidence-ledger entry for the session's evidence view.

    Per the FTY-324 ``evidence_view`` contract this never carries raw fetched
    pages, snippets, provider output blobs, or search queries. It may carry the
    same bounded fields the decision trace already sanitizes, plus source-stated
    descriptors — a global database row description, or a page/snippet
    extraction's product identity reduced through
    :func:`~app.estimator.identity_sanitizer.sanitized_identity` (never the
    provider's raw transcription string) — so the session sees the evidence
    surface it is being asked to interpret instead of a status label alone.
    """

    tier: str
    outcome: str
    source_ref: str | None = None
    decision: str | None = None
    query_variant: int | None = None
    search_status: str | None = None
    result_count: int | None = None
    source_desc: str | None = None
    surface: str | None = None

    def as_label(self) -> str:
        """Render the record as one sanitized evidence-view prompt line.

        Provider calls may carry raw diary text but nothing else raw (FTY-325
        security requirement), so every field passes through the decision-trace
        sanitizers here — at the egress seam — rather than trusting the caller:
        a ``source_ref`` embedding a URL keeps only scheme/host/path with
        secret-looking material redacted, labels and descriptors are bounded and
        redacted, and counts are clamped before rendering.
        """

        base = f"{sanitize_trace_label(self.tier)}: {sanitize_trace_label(self.outcome)}"
        ref = "" if self.source_ref is None else sanitize_trace_source_ref(self.source_ref)
        if ref:
            base = f"{base} ({ref})"
        details = _evidence_details(self)
        return f"{base}; {'; '.join(details)}" if details else base


def _evidence_details(record: EvidenceRecord) -> tuple[str, ...]:
    """Sanitized optional evidence fields rendered after the status/ref prefix."""

    details: list[str] = []
    for key, value in (
        ("decision", record.decision),
        ("query_variant", record.query_variant),
        ("search_status", record.search_status),
        ("result_count", record.result_count),
        ("surface", record.surface),
    ):
        if value is None:
            continue
        if isinstance(value, int):
            rendered = str(_clamp_evidence_count(value))
        else:
            rendered = sanitize_trace_label(value)
        if rendered:
            details.append(f"{key}={rendered}")
    if record.source_desc:
        desc = sanitize_trace_label(record.source_desc, max_len=MAX_TRACE_DESC_LEN)
        if desc:
            details.append(f'source_desc="{desc}"')
    return tuple(details)


def _clamp_evidence_count(value: int) -> int:
    return max(0, min(value, _MAX_EVIDENCE_COUNT))

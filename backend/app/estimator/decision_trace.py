"""Sanitized structured decision-trace entries for estimation runs (FTY-255).

The run ``trace`` historically recorded only coarse step labels
(``{"step", "status"}``), so diagnosing a web-evidence miss required product-cache
queries and ad hoc search/fetch probes. This module owns the **bounded, sanitized
structured entries** the food-resolution steps now append alongside those step
labels: which source tier saw a candidate, which non-secret source reference was
considered, and why the resolver accepted, rejected, deferred, or clarified.

Every value that enters an entry passes through a sanitizer here, so the trace can
never carry raw event text, prompts, secrets, fetched page content, or source
payload bodies (security baseline + ``docs/security/data-retention.md``):

- **labels** are length-bounded, control-character-stripped, and redacted of
  secret-looking material (``key=…`` pairs, bearer tokens, long opaque blobs);
- **source refs** keep only the source prefix plus a URL's scheme/host/path — the
  query string, fragment, and userinfo are dropped so a credential-bearing result
  URL cannot leak through the trace;
- **counts** are clamped to a small non-negative range;
- the entry **keys are a closed set** — an unknown field is a programming error,
  not a new channel.

The trace itself is bounded per run: once :data:`MAX_TRACE_ENTRIES` is reached a
single ``trace_truncated`` marker is appended and further decisions are dropped.
The entry vocabulary is documented in ``docs/contracts/estimation-jobs.md``
(**Decision trace**).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.estimator.food_serving import _COUNT_UNITS, _MASS_UNIT_GRAMS, _VOLUME_UNIT_GRAMS

#: Hard per-run bound on trace entries (step labels + decision entries). Generous
#: for real events (a candidate produces tens of entries at most) while capping an
#: adversarial many-candidate event; documented tunable.
MAX_TRACE_ENTRIES = 200

#: Bound on a sanitized label value (tiers, outcomes, statuses are short fixed
#: vocabulary; the bound is defence in depth for values derived from input).
MAX_TRACE_LABEL_LEN = 64

#: Bound on a sanitized source description (a global source row's product
#: description, e.g. an FDC description — global source data, never user text).
MAX_TRACE_DESC_LEN = 80

#: Bound on a sanitized source reference; matches ``evidence_sources.source_ref``
#: (``String(128)``) so a trace ref is never more detailed than persisted evidence.
MAX_TRACE_REF_LEN = 128

#: Clamp for count-like fields (result counts, indexes); trace counts are small.
_MAX_TRACE_COUNT = 9_999

#: The marker entry appended exactly once when the per-run bound is reached.
TRACE_TRUNCATED_DECISION = "trace_truncated"

#: The ``amount_kind`` vocabulary: how a candidate's parsed quantity classifies
#: without copying the quantity text itself into the trace.
AMOUNT_KINDS = ("mass", "volume", "count", "missing", "unknown")

#: Secret-looking material is redacted from every label before it enters the
#: trace: explicit ``key=value``-style credential assignments, bearer tokens,
#: ``sk-``-style provider keys, and long opaque token blobs.
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|apikey|secret|token|password|passwd|credential|authorization)\b"
        r"\s*[=:]\s*\S+"
    ),
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b[A-Za-z0-9+/_-]{40,}\b"),
)

_REDACTED = "[redacted]"

#: Control characters (incl. DEL) are stripped so multi-line/structured content
#: cannot be smuggled into a one-line label.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

#: The closed set of decision-entry fields and how each value is sanitized.
#: ``step`` and ``decision`` are implicit on every entry.
_LABEL_FIELDS = frozenset({"amount_kind", "tier", "search_status", "surface", "outcome"})
_COUNT_FIELDS = frozenset({"candidate_index", "query_variant", "result_count"})
_BOOL_FIELDS = frozenset({"has_brand"})
_REF_FIELDS = frozenset({"source_ref"})
_DESC_FIELDS = frozenset({"source_desc"})
_ALLOWED_FIELDS = _LABEL_FIELDS | _COUNT_FIELDS | _BOOL_FIELDS | _REF_FIELDS | _DESC_FIELDS

#: Field order within an entry, for stable serialized output in tests and audits.
_FIELD_ORDER = (
    "candidate_index",
    "has_brand",
    "amount_kind",
    "tier",
    "query_variant",
    "search_status",
    "result_count",
    "source_ref",
    "source_desc",
    "surface",
    "outcome",
)


def _redact_secrets(text: str) -> str:
    """Redact secret-looking material (:data:`_SECRET_PATTERNS`) from ``text``."""

    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def sanitize_trace_label(value: object, *, max_len: int = MAX_TRACE_LABEL_LEN) -> str:
    """Return ``value`` as a bounded, control-free, secret-redacted label."""

    text = _redact_secrets(_CONTROL_CHARS.sub(" ", str(value)))
    text = " ".join(text.split())
    return text[:max_len]


def sanitize_trace_source_ref(ref: object) -> str:
    """Return a bounded, non-secret source reference.

    A plain source id (``usda_fdc:12345``, ``model_prior``) passes through with
    control characters stripped. A reference embedding a URL (``official_source:
    https://…`` or a bare URL) keeps only the scheme, host, and path: the query
    string, fragment, and userinfo are dropped, and each remaining path segment
    is redacted of secret-looking material (an untrusted result URL can carry a
    token in its path, not just its query string). The result is truncated to
    :data:`MAX_TRACE_REF_LEN`.
    """

    text = _CONTROL_CHARS.sub("", str(ref)).strip()
    scheme_at = text.find("://")
    if scheme_at != -1:
        # Split an optional "<source_type>:" prefix off the embedded URL.
        prefix_end = text.rfind(":", 0, scheme_at)
        prefix = text[: prefix_end + 1] if prefix_end != -1 else ""
        url = text[prefix_end + 1 :] if prefix_end != -1 else text
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        # Redact per segment: the opaque-blob pattern must see one segment at a
        # time, or any ≥40-char path would match as a single "/"-joined blob.
        path = "/".join(_redact_secrets(segment) for segment in parts.path.split("/"))
        text = _redact_secrets(prefix) + urlunsplit((parts.scheme, host, path, "", ""))
    else:
        # No URL embedded; still redact secret-looking material defensively.
        text = _redact_secrets(text)
    return text[:MAX_TRACE_REF_LEN]


def amount_kind(unit: str | None, amount: float | None, quantity_text: str) -> str:
    """Classify a candidate's parsed quantity without copying its text.

    Returns one of :data:`AMOUNT_KINDS`: ``mass``/``volume`` for a recognised
    measured unit, ``count`` for a counted portion (a bare amount or a counted
    unit/serving noun), ``missing`` when the candidate states no amount at all,
    and ``unknown`` for an unrecognised unit or an amountless quantity phrase
    the classifier cannot place.
    """

    normalized = (unit or "").strip().lower()
    if normalized:
        if normalized in _MASS_UNIT_GRAMS:
            kind = "mass"
        elif normalized in _VOLUME_UNIT_GRAMS:
            kind = "volume"
        elif normalized in _COUNT_UNITS:
            kind = "count"
        else:
            kind = "unknown"
        return kind
    if amount is not None and amount > 0:
        return "count"
    return "unknown" if quantity_text.strip() else "missing"


def build_decision_entry(step: str, decision: str, **fields: object) -> dict[str, Any]:
    """Build one sanitized, bounded decision entry from whitelisted fields.

    ``None`` values are omitted. An unknown field name raises ``ValueError`` —
    the field set is a closed contract, not an open channel.
    """

    unknown = set(fields) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unknown decision-trace fields: {sorted(unknown)}")

    entry: dict[str, Any] = {
        "step": sanitize_trace_label(step),
        "decision": sanitize_trace_label(decision),
    }
    for key in _FIELD_ORDER:
        if key not in fields or fields[key] is None:
            continue
        value = fields[key]
        if key in _BOOL_FIELDS:
            entry[key] = bool(value)
        elif key in _COUNT_FIELDS:
            entry[key] = max(0, min(int(value), _MAX_TRACE_COUNT))  # type: ignore[call-overload]
        elif key in _REF_FIELDS:
            entry[key] = sanitize_trace_source_ref(value)
        elif key in _DESC_FIELDS:
            entry[key] = sanitize_trace_label(value, max_len=MAX_TRACE_DESC_LEN)
        else:
            entry[key] = sanitize_trace_label(value)
    return entry

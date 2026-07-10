"""Shared official-source search provider models and protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

#: Source-system id for the official-source tier (``docs/contracts/evidence-retrieval.md``
#: Version section). The configured search backend feeds this hierarchy slot.
OFFICIAL_SOURCE = "official_source"

#: Source-hierarchy classification recorded on official-source evidence rows.
OFFICIAL_SOURCE_TYPE = "official_source"

#: Lookup kinds the official-source search serves.
SEARCH_KINDS: tuple[str, ...] = ("named_product", "restaurant_item")


class SearchStatus(StrEnum):
    """The outcome of one search lookup, aligned with the FTY-045 status vocabulary.

    These are the values the adapter surfaces to its caller (FTY-062), mapping
    cleanly onto the evidence-retrieval ``Provider Capability / Status`` table:

    - :attr:`DISABLED` — provider turned off by self-host config.
    - :attr:`UNAVAILABLE` — provider not configured / missing credentials.
    - :attr:`RATE_LIMITED` — provider returned a rate-limit / quota signal.
    - :attr:`FAILED` — timeout, connection error, 5xx, 4xx, non-conforming, or
      policy-blocked response; nothing from this lookup is trusted.
    - :attr:`PARTIAL` — the provider answered but yielded no usable candidate URL.
    - :attr:`SUCCESS` — a usable list of candidate result URLs was returned.
    """

    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"
    PARTIAL = "partial"
    SUCCESS = "success"


@dataclass(frozen=True)
class SearchCandidate:
    """One candidate official-source result: a fetchable URL, title, and snippet.

    Treated as **untrusted** by the caller: the URL is a candidate for the
    hardened fetch step (FTY-078), and the title/snippet text is never trusted
    as nutrition facts — it may only become facts through the same bounded,
    schema-validated extraction the fetched page goes through (FTY-314).
    ``snippet`` is the provider's bounded result description (SearXNG
    ``content`` / Brave ``description``); it is optional, empty when the
    provider sends none, and never required for :attr:`SearchStatus.SUCCESS`.
    """

    url: str
    title: str
    snippet: str = ""


@dataclass(frozen=True)
class SearchResult:
    """A search lookup's explicit status plus its (possibly empty) candidate list.

    ``candidates`` is non-empty only for :attr:`SearchStatus.SUCCESS`; every other
    status carries no candidates, so a caller can never mistake an off/failed
    lookup for a result.
    """

    status: SearchStatus
    candidates: tuple[SearchCandidate, ...] = ()


@dataclass(frozen=True)
class SearchCapability:
    """The search provider's static capability descriptor for diagnostics.

    Mirrors the evidence-retrieval **Provider Capability** contract so health/config
    diagnostics can surface provider state without a trial call. Carries no secret.
    """

    id: str
    source_type: str
    kinds: tuple[str, ...]
    enabled: bool
    available: bool


@runtime_checkable
class SearchProvider(Protocol):
    """A pluggable search backend the official-source resolver queries.

    The adapter interface: a capability/availability surface plus a single
    :meth:`search` that maps a sanitized item-identity query to candidate URLs and
    an explicit :class:`SearchStatus`.
    """

    @property
    def enabled(self) -> bool:
        """The self-host enable flag (a disabled provider is never queried)."""
        ...

    @property
    def available(self) -> bool:
        """Whether required credentials are present."""
        ...

    @property
    def capability(self) -> SearchCapability:
        """The static capability descriptor surfaced in diagnostics."""
        ...

    def search(self, query: str) -> SearchResult:
        """Return candidate result URLs + status for ``query`` (sanitized internally)."""
        ...

"""USDA FoodData Central (FDC) evidence source for generic foods (FTY-044).

This is the trusted-nutrition-database adapter in the source hierarchy
(``docs/architecture/system-overview.md``). It turns a sanitized food *name* into
canonical per-100g facts through a hardened, allowlisted HTTPS client:

- **Config** (:class:`FdcSettings`) is read from ``FATTY_FDC_``-prefixed environment
  variables, mirroring the LLM provider config. The API key is a
  :class:`~pydantic.SecretStr`, read from the environment only, never logged or sent
  to clients. With no key configured the source is **disabled** and food candidates
  are left unresolved (the offline bundled-dataset fallback is a documented deferral).
- **Transport** goes through :mod:`app.estimator.hardened_fetch`: HTTPS only, the
  configured FDC host allowlisted, SSRF/private-network blocking, no redirects, and
  bounded time/size. The key travels in the ``X-Api-Key`` header (never the query
  string), so it cannot leak through a logged URL.
- **Sanitization**: only the normalized food name is sent — never the user's profile,
  weight, history, or any other personal context.
- **Trust boundary**: the FDC JSON is untrusted until it validates against
  :class:`FdcSearchResponse`; only Foundation / SR Legacy data types are requested so
  nutrient values are per 100 g, and a result without an energy value is skipped.
"""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from app.estimator.evidence_utils import _content_hash
from app.estimator.fdc_ranking import fdc_preference_key, is_fdc_description_compatible
from app.estimator.food_serving import NutritionFacts, nutrition_facts_plausible
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
    Resolver,
    post_json,
)

#: FDC settings are read from variables with this prefix, e.g. ``FATTY_FDC_API_KEY``.
ENV_PREFIX = "FATTY_FDC_"

#: Default FDC API base (data.gov). Overridable for self-host proxies via env.
DEFAULT_FDC_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

#: Stable identifier recorded as the cached product's source and on run evidence.
FDC_SOURCE = "usda_fdc"

#: Source-hierarchy classification recorded on evidence rows (trusted DB tier).
FDC_SOURCE_TYPE = "trusted_nutrition_database"

#: Data types whose nutrient values are reported per 100 g (deterministic serving
#: math depends on this). Branded foods report per-serving and are excluded in v1.
_FDC_DATA_TYPES: Final[tuple[str, ...]] = ("Foundation", "SR Legacy")

#: FDC nutrient ids for the v1 facts. Energy is required; macros default to 0.
_ENERGY_KCAL_ID: Final[int] = 1008
_PROTEIN_ID: Final[int] = 1003
_CARBS_ID: Final[int] = 1005
_FAT_ID: Final[int] = 1004

#: Bound the description we persist from the (untrusted) FDC payload.
_MAX_DESCRIPTION_LEN: Final[int] = 300

#: Collapse a food name to a stable cache/query key.
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


class FdcTransientError(Exception):
    """A retryable FDC failure (timeout, connection error, or 5xx)."""


class FdcResponseError(Exception):
    """A non-retryable FDC failure (4xx, oversized/non-JSON body, policy violation)."""


@dataclass(frozen=True)
class ProductFacts:
    """Canonical per-100g facts for a generic food plus its source provenance.

    Returned by a :class:`FoodSource` lookup and cached as a global ``products`` row.
    ``query_key`` is the normalized food name that produced it (the cache key);
    ``source_ref`` is the stable source id (``usda_fdc:<fdcId>``); ``content_hash``
    fingerprints the facts so evidence records are reproducible. ``facts`` carries no
    user data — it is a global source fact.
    """

    source: str
    source_ref: str
    query_key: str
    description: str
    facts: NutritionFacts
    default_serving_g: float | None
    content_hash: str
    #: The normalized barcode for a product-database (Open Food Facts) row, used as
    #: the explicit ``products.barcode`` key. ``None`` for name-keyed sources (FDC).
    barcode: str | None = None


@runtime_checkable
class FoodSource(Protocol):
    """A generic-food nutrition source the resolver queries (real FDC or a test fake)."""

    @property
    def enabled(self) -> bool:
        """Whether the source is configured and may be queried."""
        ...

    def lookup(self, query: str) -> ProductFacts | None:
        """Return per-100g facts for ``query``, or ``None`` if no confident match.

        Raises :class:`FdcTransientError` on a retryable failure and
        :class:`FdcResponseError` on a non-retryable one.
        """
        ...


def normalize_query(name: str) -> str:
    """Lower-case and collapse whitespace to a stable cache/query key."""

    return _WHITESPACE_RE.sub(" ", name.strip().lower())


class FdcSettings(BaseModel):
    """Validated FDC client configuration, read from ``FATTY_FDC_`` env vars.

    Frozen and ``extra="forbid"`` so config is immutable and unknown keys are
    rejected. The base URL must be ``https`` (the hardened fetch refuses anything
    else); the host is derived from it for the request allowlist.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: SecretStr | None = None
    base_url: str = DEFAULT_FDC_BASE_URL
    #: Per-request wall-clock timeout. A documented tunable.
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    #: Number of search results inspected for an energy-bearing match.
    max_results: int = Field(default=5, ge=1, le=25)

    @model_validator(mode="after")
    def _require_https_base_url(self) -> FdcSettings:
        """Fail closed on a non-https base URL (the hardened fetch would reject it)."""

        if not self.base_url.lower().startswith("https://"):
            raise ValueError("FATTY_FDC_BASE_URL must be an https URL")
        return self

    @property
    def is_configured(self) -> bool:
        """Whether an API key is present, i.e. the source may be queried."""

        return self.api_key is not None and bool(self.api_key.get_secret_value())

    @property
    def search_url(self) -> str:
        """The FDC ``/foods/search`` endpoint for the configured base URL."""

        return f"{self.base_url.rstrip('/')}/foods/search"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """The single allowlisted host (derived from the base URL) for fetches."""

        host = urlsplit(self.base_url).hostname or ""
        return frozenset({host.lower()})


def load_fdc_settings(environ: Mapping[str, str] | None = None) -> FdcSettings:
    """Build :class:`FdcSettings` from ``FATTY_FDC_``-prefixed variables."""

    source = os.environ if environ is None else environ
    data: dict[str, str] = {}
    for field in FdcSettings.model_fields:
        key = ENV_PREFIX + field.upper()
        if key in source:
            data[field] = source[key]
    return FdcSettings.model_validate(data)


class FdcNutrient(BaseModel):
    """One nutrient value from an FDC food (untrusted; only id+value are used)."""

    model_config = ConfigDict(extra="ignore")

    nutrientId: int | None = None
    value: float | None = None


class FdcFood(BaseModel):
    """A single FDC search result (untrusted; extra fields ignored)."""

    model_config = ConfigDict(extra="ignore")

    fdcId: int
    description: str = Field(default="")
    foodNutrients: list[FdcNutrient] = Field(default_factory=list)
    servingSize: float | None = None
    servingSizeUnit: str | None = Field(default=None, max_length=32)

    @field_validator("description", mode="before")
    @classmethod
    def _truncate_description(cls, value: Any) -> Any:
        """Truncate (not reject) an over-long description from the untrusted FDC payload.

        A long product name is cosmetic; rejecting an otherwise-usable energy-bearing
        row over a display string needlessly drops a real match. Non-string values fall
        through to normal validation, which fails closed into FdcResponseError.
        """
        if isinstance(value, str):
            return value[:_MAX_DESCRIPTION_LEN]
        return value


class FdcSearchResponse(BaseModel):
    """The validated shape of an FDC ``/foods/search`` reply (untrusted until here)."""

    model_config = ConfigDict(extra="ignore")

    foods: list[FdcFood] = Field(default_factory=list)


# Transport callable signature, injectable so tests drive a network-free fake.
class _Transport(Protocol):
    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
        allowed_hosts: frozenset[str],
        resolver: Resolver,
    ) -> dict[str, Any]: ...


def _default_transport(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
    allowed_hosts: frozenset[str],
    resolver: Resolver,
) -> dict[str, Any]:
    return post_json(
        url,
        headers=headers,
        payload=payload,
        timeout_seconds=timeout_seconds,
        allowed_hosts=allowed_hosts,
        resolver=resolver,
    )


class FdcClient:
    """Hardened, allowlisted USDA FoodData Central client.

    Disabled (``enabled is False``) when no API key is configured, in which case the
    resolver leaves food candidates unresolved. The ``transport`` and ``resolver``
    seams let tests exercise the full mapping with no network or DNS.
    """

    def __init__(
        self,
        settings: FdcSettings,
        *,
        transport: _Transport = _default_transport,
        resolver: Resolver | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        # Default to real DNS resolution when no resolver seam is injected.
        self._resolver = resolver or socket.getaddrinfo

    @property
    def enabled(self) -> bool:
        return self._settings.is_configured

    def lookup(self, query: str) -> ProductFacts | None:
        """Search FDC for ``query`` and return the best-ranked compatible match.

        Only the sanitized food name is sent. Returns ``None`` when the source is
        disabled, no result carries an energy value, or no result names the queried
        food in a compatible form (FTY-254 — see :mod:`app.estimator.fdc_ranking`).
        Maps transport/policy failures to :class:`FdcTransientError` /
        :class:`FdcResponseError`.
        """

        response = self._search(query)
        if response is None:
            return None
        return self._first_match(normalize_query(query), response)

    def list_matches(self, query: str) -> list[ProductFacts]:
        """Search FDC for ``query`` and return **every** energy-bearing match.

        The list-candidates counterpart to :meth:`lookup` (FTY-093 re-match): instead
        of taking only the first energy-bearing food, it maps *all* of them — up to the
        ``max_results`` page bound — so the re-match capability can surface alternative
        source matches beyond the resolver's first pick. Only the sanitized food name is
        sent; energy-less results are excluded (a fact set with no energy is not an
        offerable match). Unlike :meth:`lookup`, no FTY-254 compatibility ranking is
        applied — re-match deliberately surfaces every alternative for the user to
        choose from. Returns ``[]`` when the source is disabled or nothing matches.
        Maps transport/policy failures to :class:`FdcTransientError` /
        :class:`FdcResponseError`, exactly like :meth:`lookup`.
        """

        response = self._search(query)
        if response is None:
            return []
        normalized = normalize_query(query)
        return [
            facts
            for food in response.foods
            if (facts := _food_to_facts(normalized, food)) is not None
        ]

    def _search(self, query: str) -> FdcSearchResponse | None:
        """Issue and validate a /foods/search request for ``query``.

        Returns ``None`` when the source is disabled or the query normalizes to empty.
        Raises :class:`FdcTransientError` / :class:`FdcResponseError` on transport or
        validation failures — ``ValidationError`` is mapped to :class:`FdcResponseError`
        so a malformed body never escapes as an uncaught exception.
        """

        if not self.enabled:
            return None

        normalized = normalize_query(query)
        if not normalized:
            return None

        # The key rides in the header, never the URL/query string, so it cannot leak
        # through a logged request line. ``enabled`` guarantees it is present.
        api_key = self._settings.api_key
        if api_key is None:
            return None

        payload = {
            "query": normalized,
            "dataType": list(_FDC_DATA_TYPES),
            "pageSize": self._settings.max_results,
        }
        headers = {"X-Api-Key": api_key.get_secret_value()}

        try:
            raw = self._transport(
                self._settings.search_url,
                headers=headers,
                payload=payload,
                timeout_seconds=self._settings.timeout_seconds,
                allowed_hosts=self._settings.allowed_hosts,
                resolver=self._resolver,
            )
        except FetchTransientError as exc:
            raise FdcTransientError("fdc_transient_error") from exc
        except (FetchResponseError, FetchPolicyError) as exc:
            raise FdcResponseError("fdc_response_error") from exc

        try:
            return FdcSearchResponse.model_validate(raw)
        except ValidationError as exc:
            raise FdcResponseError("fdc_response_error") from exc

    @staticmethod
    def _first_match(query_key: str, response: FdcSearchResponse) -> ProductFacts | None:
        """Select the best-ranked compatible energy-bearing FDC food, or ``None``.

        FTY-254: a trusted-database match must be the queried food in a
        compatible form, not merely USDA's top lexical hit. Each energy-bearing,
        plausible row must pass :func:`is_fdc_description_compatible` (head-noun
        identity, no unstated density-changing form, stated added ingredients
        present); the survivors are ordered by :func:`fdc_preference_key`
        (common/fresh/simple forms first, then query-token coverage), with the
        source's own relevance order as the tie-break. Rejecting every row is a
        clean miss, so the resolver falls forward to the rough-estimate tiers
        instead of costing the wrong food.
        """

        ranked: list[tuple[tuple[int, int], int, ProductFacts]] = []
        for index, food in enumerate(response.foods):
            facts = _food_to_facts(query_key, food)
            if facts is None:
                continue
            if not is_fdc_description_compatible(query_key, food.description):
                continue
            ranked.append((fdc_preference_key(query_key, food.description), index, facts))
        if not ranked:
            return None
        return min(ranked)[2]


def _food_to_facts(query_key: str, food: FdcFood) -> ProductFacts | None:
    """Map one FDC food to canonical per-100g :class:`ProductFacts`, or ``None``.

    Returns ``None`` for a food with no per-100g energy (kcal) value, which cannot be
    costed deterministically and is therefore not an offerable match. Shared by the
    first-match resolver (:meth:`FdcClient._first_match`) and the list-candidates path
    (:meth:`FdcClient.list_matches`) so both classify a food identically.
    """

    values = {
        n.nutrientId: n.value
        for n in food.foodNutrients
        if n.nutrientId is not None and n.value is not None
    }
    energy = values.get(_ENERGY_KCAL_ID)
    if energy is None:
        return None
    facts = NutritionFacts(
        calories=float(energy),
        protein_g=float(values.get(_PROTEIN_ID, 0.0)),
        carbs_g=float(values.get(_CARBS_ID, 0.0)),
        fat_g=float(values.get(_FAT_ID, 0.0)),
    )
    if not nutrition_facts_plausible(facts):
        return None
    source_ref = f"{FDC_SOURCE}:{food.fdcId}"
    return ProductFacts(
        source=FDC_SOURCE,
        source_ref=source_ref,
        query_key=query_key,
        description=food.description,
        facts=facts,
        default_serving_g=_serving_grams(food),
        content_hash=_content_hash(source_ref, facts),
    )


def _serving_grams(food: FdcFood) -> float | None:
    """The food's default serving in grams, or ``None`` if not a gram/ml measure.

    Only mass (``g``) and water-density volume (``ml``) servings are trusted as a
    gram default; anything else leaves count-based quantities unresolved (the caller
    then routes to ``needs_clarification``).
    """

    if food.servingSize is None or food.servingSize <= 0:
        return None
    unit = (food.servingSizeUnit or "").strip().lower()
    if unit in {"g", "gram", "grams"}:
        return food.servingSize
    if unit in {"ml", "milliliter", "millilitre"}:
        return food.servingSize  # 1 ml ≈ 1 g (documented v1 assumption)
    return None


def build_fdc_client(settings: FdcSettings | None = None) -> FdcClient:
    """Build the default :class:`FdcClient` from environment-loaded settings."""

    return FdcClient(settings or load_fdc_settings())

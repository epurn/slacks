"""Open Food Facts (OFF) barcode evidence source for packaged products (FTY-060).

This is the ``product_database`` adapter in the evidence-retrieval source hierarchy
(``docs/contracts/evidence-retrieval.md``), sitting **above** the USDA FDC generic
source: a confident OFF product match for a scanned barcode is a packaged-product
fact and is preferred over a generic USDA estimate for the same input. It turns a
normalized **barcode** (UPC/EAN) into canonical per-100g facts through a hardened,
allowlisted HTTPS client:

- **Config** (:class:`OffSettings`) is read from ``SLACKS_OFF_``-prefixed environment
  variables, mirroring the FDC config. OFF is an *open* API needing no key, so the
  source is **enabled by default**; a self-hoster disables it with
  ``SLACKS_OFF_ENABLED=false``. An optional, non-secret ``user_agent`` honours OFF's
  identifying-client etiquette.
- **Transport** goes through :func:`app.estimator.hardened_fetch.get_json`: HTTPS
  only, the configured OFF host allowlisted, SSRF/private-network blocking, no
  redirects, and bounded time/size. OFF is queried **by barcode only**.
- **Data minimization**: only the normalized barcode reaches OFF — never the user's
  profile, weight, history, or any other personal context. A barcode carries no
  personal data, but the query is sanitized (digits only) anyway.
- **Trust boundary**: the OFF JSON is untrusted until it validates against
  :class:`OffProductResponse`; the product must carry a usable per-100g (or
  per-serving + gram serving size) **energy** value or it is treated as a non-match
  and routed deterministically rather than guessed.

OFF data quality is uneven: products may lack energy or macros, or carry
per-serving-only facts. The mapping requires energy kcal (per 100 g, or per serving
with a gram serving size to convert), defaults missing macros to 0 (mirroring FDC),
and treats anything else as a non-match. These thresholds are documented tunables.
"""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Mapping
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.estimator.evidence_utils import _content_hash
from app.estimator.fdc import ProductFacts
from app.estimator.food_serving import NutritionFacts, nutrition_facts_plausible
from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
    Resolver,
    get_json,
)

#: OFF settings are read from variables with this prefix, e.g. ``SLACKS_OFF_BASE_URL``.
ENV_PREFIX = "SLACKS_OFF_"

#: Default OFF API base. Overridable for self-host proxies/mirrors via env.
DEFAULT_OFF_BASE_URL = "https://world.openfoodfacts.org"

#: A non-secret default identifying user-agent, per OFF's API etiquette. A
#: self-hoster can override it (e.g. with a contact address) via env.
DEFAULT_OFF_USER_AGENT = "Slacks/1.0 (+https://github.com/epurn/slacks)"

#: Stable identifier recorded as the cached product's source and on run evidence.
OFF_SOURCE = "open_food_facts"

#: Source-hierarchy classification recorded on evidence rows (product-database tier).
OFF_SOURCE_TYPE = "product_database"

#: OFF "product found" status flag in the response body.
_OFF_STATUS_FOUND: Final[int] = 1

#: Bound the description we persist from the (untrusted) OFF payload.
_MAX_DESCRIPTION_LEN: Final[int] = 300

#: Valid GTIN/UPC/EAN digit lengths (EAN-8, UPC-A, EAN-13, GTIN-14).
_VALID_BARCODE_LENGTHS: Final[frozenset[int]] = frozenset({8, 12, 13, 14})

#: Strip any non-digit separators a barcode might be written with.
_NON_DIGITS_RE: Final[re.Pattern[str]] = re.compile(r"\D")


class OffTransientError(Exception):
    """A retryable OFF failure (timeout, connection error, or 5xx)."""


class OffResponseError(Exception):
    """A non-retryable OFF failure (4xx, oversized/non-JSON body, policy violation)."""


def normalize_barcode(barcode: str | None) -> str | None:
    """Return the sanitized, digits-only barcode, or ``None`` if it is not valid.

    Strips any separators and rejects anything that is not a plausible UPC/EAN
    (8/12/13/14 digits). A non-valid barcode resolves to ``None`` so the caller routes
    deterministically rather than calling OFF with garbage.
    """

    if not barcode:
        return None
    digits = _NON_DIGITS_RE.sub("", barcode)
    if len(digits) not in _VALID_BARCODE_LENGTHS:
        return None
    return digits


@runtime_checkable
class BarcodeSource(Protocol):
    """A barcode nutrition source the resolver queries (real OFF or a test fake)."""

    @property
    def enabled(self) -> bool:
        """Whether the source is enabled and may be queried."""
        ...

    def lookup(self, barcode: str) -> ProductFacts | None:
        """Return per-100g facts for ``barcode``, or ``None`` if no confident match.

        Raises :class:`OffTransientError` on a retryable failure and
        :class:`OffResponseError` on a non-retryable one.
        """
        ...


class OffSettings(BaseModel):
    """Validated OFF client configuration, read from ``SLACKS_OFF_`` env vars.

    Frozen and ``extra="forbid"`` so config is immutable and unknown keys are
    rejected. The base URL must be ``https`` (the hardened fetch refuses anything
    else); the host is derived from it for the request allowlist. OFF needs no key,
    so it is enabled by default and a self-hoster opts out with ``enabled=false``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Self-host enable/disable flag. OFF is an open API, so it is on by default.
    enabled: bool = True
    base_url: str = DEFAULT_OFF_BASE_URL
    #: Per-request wall-clock timeout. A documented tunable.
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    #: Non-secret identifying user-agent sent to OFF (API etiquette / rate limits).
    user_agent: str = Field(default=DEFAULT_OFF_USER_AGENT, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _require_https_base_url(self) -> OffSettings:
        """Fail closed on a non-https base URL (the hardened fetch would reject it)."""

        if not self.base_url.lower().startswith("https://"):
            raise ValueError("SLACKS_OFF_BASE_URL must be an https URL")
        return self

    @property
    def is_available(self) -> bool:
        """Whether the source has the config it needs (OFF needs no credentials)."""

        return True

    def product_url(self, barcode: str) -> str:
        """The OFF v2 product endpoint for ``barcode`` (already normalized).

        ``fields`` is pinned to the nutrition facts we actually use, which both
        minimizes the response and bounds what crosses the boundary.
        """

        base = self.base_url.rstrip("/")
        fields = "code,product_name,nutriments,serving_quantity,serving_size"
        return f"{base}/api/v2/product/{barcode}.json?fields={fields}"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """The single allowlisted host (derived from the base URL) for fetches."""

        host = urlsplit(self.base_url).hostname or ""
        return frozenset({host.lower()})


def load_off_settings(environ: Mapping[str, str] | None = None) -> OffSettings:
    """Build :class:`OffSettings` from ``SLACKS_OFF_``-prefixed variables."""

    source = os.environ if environ is None else environ
    data: dict[str, str] = {}
    for field in OffSettings.model_fields:
        key = ENV_PREFIX + field.upper()
        if key in source:
            data[field] = source[key]
    return OffSettings.model_validate(data)


class OffNutriments(BaseModel):
    """The nutriment subset we use from an OFF product (untrusted; extras ignored).

    OFF reports both per-100g (``*_100g``) and per-serving (``*_serving``) values; the
    hyphenated energy keys are mapped via aliases. Values are coerced to floats; a
    non-numeric value fails validation (the response is then treated as unusable).
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    energy_kcal_100g: float | None = Field(default=None, alias="energy-kcal_100g")
    proteins_100g: float | None = None
    carbohydrates_100g: float | None = None
    fat_100g: float | None = None
    energy_kcal_serving: float | None = Field(default=None, alias="energy-kcal_serving")
    proteins_serving: float | None = None
    carbohydrates_serving: float | None = None
    fat_serving: float | None = None


class OffProduct(BaseModel):
    """A single OFF product payload (untrusted; only the used fields are trusted)."""

    model_config = ConfigDict(extra="ignore")

    product_name: str = Field(default="")
    nutriments: OffNutriments = Field(default_factory=OffNutriments)
    #: Serving size in grams when OFF supplies one (count-unit serving math).
    serving_quantity: float | None = None

    @field_validator("product_name", mode="before")
    @classmethod
    def _truncate_product_name(cls, value: Any) -> Any:
        """Truncate (not reject) an over-long product name from the untrusted OFF payload.

        A long product name is cosmetic; rejecting an otherwise-usable energy-bearing
        row over a display string needlessly drops a real match. Non-string values fall
        through to normal validation, which fails closed into OffResponseError.
        """
        if isinstance(value, str):
            return value[:_MAX_DESCRIPTION_LEN]
        return value


class OffProductResponse(BaseModel):
    """The validated shape of an OFF ``/api/v2/product/<barcode>.json`` reply."""

    model_config = ConfigDict(extra="ignore")

    status: int = 0
    product: OffProduct | None = None


# Transport callable signature, injectable so tests drive a network-free fake.
class _Transport(Protocol):
    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout_seconds: float,
        allowed_hosts: frozenset[str],
        resolver: Resolver,
    ) -> dict[str, Any]: ...


def _default_transport(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    allowed_hosts: frozenset[str],
    resolver: Resolver,
) -> dict[str, Any]:
    return get_json(
        url,
        headers=headers,
        timeout_seconds=timeout_seconds,
        allowed_hosts=allowed_hosts,
        resolver=resolver,
    )


class OffClient:
    """Hardened, allowlisted Open Food Facts barcode client.

    Disabled (``enabled is False``) when a self-hoster turns the source off, in which
    case the resolver falls back to the next source. The ``transport`` and
    ``resolver`` seams let tests exercise the full mapping with no network or DNS.
    """

    def __init__(
        self,
        settings: OffSettings,
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
        return self._settings.enabled and self._settings.is_available

    def lookup(self, barcode: str) -> ProductFacts | None:
        """Look up ``barcode`` on OFF and map the first usable product to facts.

        Only the normalized, digits-only barcode is sent. Returns ``None`` when the
        source is disabled, the barcode is invalid, the product is not found, or it
        carries no usable energy value. Maps transport/policy failures to
        :class:`OffTransientError` / :class:`OffResponseError`.
        """

        if not self.enabled:
            return None

        normalized = normalize_barcode(barcode)
        if normalized is None:
            return None

        headers = {"User-Agent": self._settings.user_agent}
        try:
            raw = self._transport(
                self._settings.product_url(normalized),
                headers=headers,
                timeout_seconds=self._settings.timeout_seconds,
                allowed_hosts=self._settings.allowed_hosts,
                resolver=self._resolver,
            )
        except FetchTransientError as exc:
            raise OffTransientError("off_transient_error") from exc
        except (FetchResponseError, FetchPolicyError) as exc:
            raise OffResponseError("off_response_error") from exc

        try:
            response = OffProductResponse.model_validate(raw)
        except ValidationError as exc:
            raise OffResponseError("off_response_error") from exc
        return _map_product(normalized, response)


def _map_product(barcode: str, response: OffProductResponse) -> ProductFacts | None:
    """Map a found OFF product to canonical per-100g :class:`ProductFacts`, or ``None``.

    Prefers per-100g facts. When OFF supplies only per-serving facts plus a gram
    serving size, converts them to per-100g for canonical storage. If neither a
    per-100g basis nor a gram serving size with energy is derivable, returns ``None``
    (a non-match, routed deterministically). Missing macros default to 0.
    """

    if response.status != _OFF_STATUS_FOUND or response.product is None:
        return None

    product = response.product
    nutriments = product.nutriments
    serving_g = product.serving_quantity if (product.serving_quantity or 0) > 0 else None

    facts = _facts_per_100g(nutriments, serving_g)
    if facts is None:
        # No energy on a usable basis: cannot compute calories deterministically.
        return None

    source_ref = f"{OFF_SOURCE}:{barcode}"
    return ProductFacts(
        source=OFF_SOURCE,
        source_ref=source_ref,
        query_key=barcode,
        description=product.product_name,
        facts=facts,
        default_serving_g=serving_g,
        content_hash=_content_hash(source_ref, facts),
        barcode=barcode,
    )


def _facts_per_100g(nutriments: OffNutriments, serving_g: float | None) -> NutritionFacts | None:
    """Derive canonical per-100g facts, preferring the per-100g basis.

    Returns ``None`` when no energy value is available on a usable basis.
    """

    if nutriments.energy_kcal_100g is not None:
        facts = NutritionFacts(
            calories=float(nutriments.energy_kcal_100g),
            protein_g=float(nutriments.proteins_100g or 0.0),
            carbs_g=float(nutriments.carbohydrates_100g or 0.0),
            fat_g=float(nutriments.fat_100g or 0.0),
        )
        return facts if nutrition_facts_plausible(facts) else None

    if nutriments.energy_kcal_serving is not None and serving_g is not None and serving_g > 0:
        # Convert per-serving facts to per-100g for canonical storage.
        factor = 100.0 / serving_g
        facts = NutritionFacts(
            calories=round(float(nutriments.energy_kcal_serving) * factor, 4),
            protein_g=round(float(nutriments.proteins_serving or 0.0) * factor, 4),
            carbs_g=round(float(nutriments.carbohydrates_serving or 0.0) * factor, 4),
            fat_g=round(float(nutriments.fat_serving or 0.0) * factor, 4),
        )
        return facts if nutrition_facts_plausible(facts) else None

    return None


def build_off_client(settings: OffSettings | None = None) -> OffClient:
    """Build the default :class:`OffClient` from environment-loaded settings."""

    return OffClient(settings or load_off_settings())

"""Evidence-source diagnostics service (FTY-060).

Builds the source-provider capability descriptors surfaced in health/config
diagnostics (``docs/contracts/evidence-retrieval.md``) from the environment-loaded
provider settings. Reads config only — never the secret values — and makes no
external calls, so it is safe on a liveness-adjacent endpoint.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping

from app.estimator.fdc import FDC_SOURCE, FDC_SOURCE_TYPE, load_fdc_settings
from app.estimator.off import OFF_SOURCE, OFF_SOURCE_TYPE, load_off_settings
from app.estimator.official_fetch import load_official_fetch_settings
from app.estimator.official_step import REFERENCE_SOURCE, REFERENCE_SOURCE_TYPE
from app.estimator.reference_fetch import load_reference_fetch_settings
from app.estimator.search import (
    OFFICIAL_SOURCE,
    OFFICIAL_SOURCE_TYPE,
    SEARCH_KINDS,
    load_search_settings,
)
from app.llm.config import load_llm_settings
from app.schemas.sources import (
    EgressPolicy,
    SearchedResultFetchPolicy,
    SourceCapability,
    SourcesStatus,
)

#: Lookup kinds the reference-source tier serves (FTY-166): branded items official
#: sources miss, plus detail-rich generic foods (which have no official page).
REFERENCE_KINDS: tuple[str, ...] = ("generic_food", "named_product", "restaurant_item")

#: Claude Code LLM provider descriptor constants.
CLAUDE_CODE_SOURCE = "claude_code"
CLAUDE_CODE_SOURCE_TYPE = "llm_provider"


def _session_present(config_dir: str) -> bool:
    """Return True if a Claude Code session file is detectable in config_dir.

    Pure filesystem check — never reads file contents, so no credential is
    examined or surfaced. A JSON file in the config dir is a proxy for a
    ``claude login`` session having been written there.
    """
    if not os.path.isdir(config_dir):
        return False
    try:
        return any(
            f.endswith(".json") and os.path.isfile(os.path.join(config_dir, f))
            for f in os.listdir(config_dir)
        )
    except OSError:
        return False


def _probe_claude_code(environ: Mapping[str, str] | None = None) -> tuple[bool, bool]:
    """Return (binary_present, session_valid) for the claude_code provider.

    Both checks are cheap, local, and content-free: no subprocess, no network
    call, no credential read. ``binary_present`` checks ``PATH`` for the ``claude``
    executable; ``session_valid`` checks whether the config dir has a session file.
    Nothing about the session content is read or surfaced.
    """
    source = os.environ if environ is None else environ

    binary_present = shutil.which("claude") is not None
    if not binary_present:
        return False, False

    config_dir = source.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))
    return True, _session_present(config_dir)


def list_source_capabilities(environ: Mapping[str, str] | None = None) -> SourcesStatus:
    """Return the capability descriptor for each configured evidence source.

    The official-source search provider (FTY-079/164) defaults to the keyless local
    SearXNG backend, so out of the box it is ``enabled`` and ``available`` with no
    API key; selecting Brave gates ``available`` on its key, and the ``none``
    provider (or ``FATTY_SEARCH_ENABLED=false``) reports enabled=false — the
    explicit opt-out. USDA FDC (generic foods) is always ``enabled`` but only
    ``available`` with an API key; Open Food Facts (barcode) needs no credentials, so
    it is always ``available`` and ``enabled`` unless a self-hoster turns it off.
    The ``claude_code`` LLM provider (FTY-087/088) is ``enabled`` when selected as
    the active provider and ``available`` when the CLI is on PATH and a session exists.
    """

    search = load_search_settings(environ)
    reference = load_reference_fetch_settings(environ)
    off = load_off_settings(environ)
    fdc = load_fdc_settings(environ)
    llm = load_llm_settings(environ)
    binary_present, session_valid = _probe_claude_code(environ)

    return SourcesStatus(
        sources=[
            SourceCapability(
                id=OFFICIAL_SOURCE,
                source_type=OFFICIAL_SOURCE_TYPE,
                kinds=list(SEARCH_KINDS),
                enabled=search.is_enabled,
                available=search.is_available,
            ),
            SourceCapability(
                id=REFERENCE_SOURCE,
                source_type=REFERENCE_SOURCE_TYPE,
                kinds=list(REFERENCE_KINDS),
                # The reference tier rides the search adapter: it is on only when both
                # the searched-result fetch and search itself are enabled, and it is
                # available exactly when search is (the fetch needs no credential).
                enabled=reference.enabled and search.is_enabled,
                available=search.is_available,
            ),
            SourceCapability(
                id=OFF_SOURCE,
                source_type=OFF_SOURCE_TYPE,
                kinds=["barcode"],
                enabled=off.enabled,
                available=off.is_available,
            ),
            SourceCapability(
                id=FDC_SOURCE,
                source_type=FDC_SOURCE_TYPE,
                kinds=["generic_food"],
                enabled=True,
                available=fdc.is_configured,
            ),
            SourceCapability(
                id=CLAUDE_CODE_SOURCE,
                source_type=CLAUDE_CODE_SOURCE_TYPE,
                kinds=["estimation"],
                enabled=llm.provider == "claude_code",
                # available = CLI on PATH AND a session file detected — booleans only,
                # no token/identity/session content ever surfaced (FTY-088 security).
                available=binary_present and session_valid,
            ),
        ]
    )


def describe_egress_policy(environ: Mapping[str, str] | None = None) -> EgressPolicy:
    """Return the evidence-fetch egress policy (FTY-078/166) for diagnostics.

    Surfaces the configured official-source host allowlist and page-fetch bounds
    (size, timeout, content types) plus the fixed hardened-fetch invariants, and the
    searched-result (reference-source) fetch policy — whether public search-result
    pages may be fetched, and under what bounds — so a self-hoster can see the SSRF /
    egress boundary without reading code. Reads config only — never a secret, never a
    URL from a user entry — and makes no external calls, so it is safe on a
    liveness-adjacent endpoint.
    """

    official = load_official_fetch_settings(environ)
    reference = load_reference_fetch_settings(environ)
    return EgressPolicy(
        allowed_hosts=sorted(official.allowed_hosts),
        max_bytes=official.max_bytes,
        timeout_seconds=official.timeout_seconds,
        allowed_content_types=sorted(official.allowed_content_types),
        searched_result_fetch=SearchedResultFetchPolicy(
            enabled=reference.enabled,
            max_bytes=reference.max_bytes,
            timeout_seconds=reference.timeout_seconds,
            allowed_content_types=sorted(reference.allowed_content_types),
        ),
    )

"""Shared builders + ``session`` fixture for the exact-evidence apply tests.

Not a test module. Extracted from ``test_exact_evidence_apply.py`` (FTY-361) so the
proposal-model/service tests (``test_exact_evidence_apply.py``) and the API-level
endpoint tests (``test_exact_evidence_apply_api.py``) import one cohesive helper
module instead of duplicating the proposal builders and the local ``session``
fixture. The builders and fixture are moved verbatim; the assertions live in the
test files that call them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import ExactEvidenceKind, ExactEvidenceQuality, SourceType
from app.estimator.exact_evidence import (
    ExactEvidenceProposal,
    ProposalFacts,
    build_proposal,
    encode_proposal_ref,
)
from app.settings import DEV_AUTH_SECRET


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _facts(
    *,
    calories: float = 120.0,
    default_serving_g: float | None = 150.0,
    serving_label: str | None = "1 serving",
) -> ProposalFacts:
    return ProposalFacts(
        basis="per_100g",
        calories=calories,
        protein_g=6.0,
        carbs_g=12.0,
        fat_g=3.0,
        default_serving_g=default_serving_g,
        serving_label=serving_label,
    )


def _exact_proposal(
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    calories: float = 120.0,
    default_serving_g: float | None = 150.0,
    source_type: str = SourceType.PRODUCT_DATABASE.value,
    source_ref: str = "open_food_facts:0123456789012",
    kind: ExactEvidenceKind = ExactEvidenceKind.BARCODE,
    now: datetime | None = None,
) -> ExactEvidenceProposal:
    return build_proposal(
        owner_id=owner_id,
        item_id=item_id,
        kind=kind,
        quality=ExactEvidenceQuality.EXACT,
        source_type=source_type,
        source_ref=source_ref,
        content_hash="hash-exact",
        facts=_facts(calories=calories, default_serving_g=default_serving_g),
        now=now,
    )


def _fallback_proposal(
    owner_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    source_type: str = SourceType.REFERENCE_SOURCE.value,
    source_ref: str = "reference_source:https://ex.example/nutrition",
    assumptions: list[str] | None = None,
    field_provenance: dict[str, str] | None = None,
) -> ExactEvidenceProposal:
    return build_proposal(
        owner_id=owner_id,
        item_id=item_id,
        kind=ExactEvidenceKind.BARCODE,
        quality=ExactEvidenceQuality.FALLBACK,
        source_type=source_type,
        source_ref=source_ref,
        content_hash="hash-fallback",
        facts=_facts(),
        assumptions=assumptions if assumptions is not None else ["barcode_no_match"],
        field_provenance=field_provenance,
    )


def _apply_url(user_id: str, item_id: uuid.UUID) -> str:
    return f"/api/users/{user_id}/derived-items/food/{item_id}/exact-upgrade/apply"


def _ref_for_app(owner_id: str, item_id: uuid.UUID, **kwargs: object) -> str:
    """Sign a proposal with the app's dev secret so the route can verify it."""

    proposal = _exact_proposal(uuid.UUID(owner_id), item_id, **kwargs)  # type: ignore[arg-type]
    return encode_proposal_ref(proposal, DEV_AUTH_SECRET)

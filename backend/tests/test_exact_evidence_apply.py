"""Exact-evidence proposal apply foundation tests (FTY-307).

Exercise the generic apply path with **stubbed** proposal facts (source-specific
barcode/label generation is FTY-308/FTY-309), proving the acceptance criteria:

- a valid **exact** proposal applies in place — same item id / log event id, updated
  calories/macros/grams, rewritten evidence source, ``*_estimated`` re-snapshotted, one
  ``re_match`` correction row, ``is_edited = false``;
- current amount is preserved by default; an explicit amount costs + audits at the
  adjusted amount, folded into the one re-resolution (no separate ``amount_adjust`` row);
- an uncostable current/adjusted amount fails closed (``amount_required``) with no mutation;
- a **fallback** proposal keeps its honest low-trust provenance + assumptions and never
  masquerades as ``user_label`` / ``product_database``;
- tampered / expired / wrong-user / wrong-item references, and any client-supplied facts,
  are rejected with no mutation;
- cross-user / unknown item / voided parent fail closed as ``404``;
- the read model reports the new source and ``is_edited = false``.

The API-level endpoint tests (the ``test_apply_api_*`` group) live in the sibling
``test_exact_evidence_apply_api.py``; the shared proposal builders and the ``session``
fixture live in ``tests.exact_evidence_helpers``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.enums import (
    CandidateType,
    CorrectionSource,
    DerivedItemStatus,
    ExactEvidenceKind,
    ExactEvidenceQuality,
    SourceType,
)
from app.estimator.exact_evidence import (
    AmountNotCostable,
    ExactEvidenceApplyCapability,
    InvalidProposalRef,
    ProposalNotResolvable,
    build_proposal,
    decode_proposal_ref,
    encode_proposal_ref,
)
from app.models.corrections import Correction
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.identity import User
from app.security.tokens import mint_token
from app.services import item_read_model
from app.services.exact_evidence import serialize_proposal
from tests.corrections_helpers import register, seed_evidence, seed_food_item
from tests.exact_evidence_helpers import _exact_proposal, _facts, _fallback_proposal
from tests.exact_evidence_helpers import session as session  # noqa: PLC0414 — re-exported fixture

SECRET = "test-proposal-secret"  # noqa: S105 (test signing key, not a real credential)


# ---------------------------------------------------------------------------
# Fixtures + builders
# ---------------------------------------------------------------------------


def _user(session: Session, user_id: str) -> User:
    user = session.get(User, uuid.UUID(user_id))
    assert user is not None
    return user


def _capability(session: Session) -> ExactEvidenceApplyCapability:
    return ExactEvidenceApplyCapability(session=session, secret=SECRET)


# ---------------------------------------------------------------------------
# (a) Signing / trust anchor round-trip
# ---------------------------------------------------------------------------


def test_encode_decode_round_trips_every_bound_field() -> None:
    owner_id, item_id = uuid.uuid4(), uuid.uuid4()
    proposal = _fallback_proposal(
        owner_id,
        item_id,
        assumptions=["barcode_no_match", "comparable_reference"],
        field_provenance={"calories": "estimated"},
    )
    decoded = decode_proposal_ref(encode_proposal_ref(proposal, SECRET), SECRET)
    assert decoded == proposal


def test_tampered_reference_is_rejected() -> None:
    proposal = _exact_proposal(uuid.uuid4(), uuid.uuid4())
    ref = encode_proposal_ref(proposal, SECRET)
    payload_b64, signature = ref.split(".")
    # Flip a payload character: the signature no longer verifies.
    tampered = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B") + "." + signature
    with pytest.raises(InvalidProposalRef):
        decode_proposal_ref(tampered, SECRET)


@pytest.mark.parametrize(
    "malformed",
    [
        "é.c2ln",  # non-ASCII payload segment: breaks _sign's ASCII encode
        "cGF5.é",  # non-ASCII signature segment: breaks compare_digest (ASCII-only)
        "é.é",  # both segments non-ASCII
    ],
)
def test_non_ascii_reference_fails_closed_not_with_a_server_error(malformed: str) -> None:
    # Untrusted, non-ASCII proposal refs must raise InvalidProposalRef (→ 422), never
    # escape as an unmapped UnicodeError/TypeError (→ 500): the fail-closed contract.
    with pytest.raises(InvalidProposalRef):
        decode_proposal_ref(malformed, SECRET)


def test_reference_signed_with_another_secret_is_rejected() -> None:
    proposal = _exact_proposal(uuid.uuid4(), uuid.uuid4())
    ref = encode_proposal_ref(proposal, "a-different-secret")
    with pytest.raises(InvalidProposalRef):
        decode_proposal_ref(ref, SECRET)


def test_auth_bearer_token_is_not_a_valid_proposal_reference() -> None:
    # The proposal ref reuses SLACKS_AUTH_SECRET, so prove domain separation: an auth
    # bearer token signed with the same secret cannot masquerade as a proposal ref.
    token = mint_token(uuid.uuid4(), SECRET, ttl_seconds=3600)
    with pytest.raises(InvalidProposalRef):
        decode_proposal_ref(token, SECRET)


def test_expired_reference_is_rejected() -> None:
    long_ago = datetime.now(UTC) - timedelta(days=1)
    proposal = _exact_proposal(uuid.uuid4(), uuid.uuid4(), now=long_ago)
    with pytest.raises(InvalidProposalRef):
        decode_proposal_ref(encode_proposal_ref(proposal, SECRET), SECRET)


# ---------------------------------------------------------------------------
# (b) Exact apply — in-place source replacement
# ---------------------------------------------------------------------------


def test_exact_apply_rewrites_evidence_resnapshots_and_records_re_match(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-exact@example.com")
    item_id = seed_food_item(
        db_engine, user_id, amount=2.0, calories=300.0, protein_g=10.0, carbs_g=40.0, fat_g=5.0
    )
    seed_evidence(db_engine, user_id, item_id, source_type="model_prior", source_ref="model_prior")
    before = session.get(DerivedFoodItem, item_id)
    assert before is not None
    log_event_id = before.log_event_id

    proposal = _exact_proposal(uuid.UUID(user_id), item_id)
    item = _capability(session).apply(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        proposal_ref=encode_proposal_ref(proposal, SECRET),
    )

    # Recomputed at the current portion: 2 × 150 g = 300 g → ×1.2 of per-100g facts.
    assert item.grams == pytest.approx(300.0)
    assert item.calories == pytest.approx(360.0)
    assert item.protein_g == pytest.approx(18.0)
    assert item.carbs_g == pytest.approx(36.0)
    assert item.fat_g == pytest.approx(9.0)
    # *_estimated RE-SNAPSHOTTED to the new source's values (re-resolution, not override).
    assert item.calories_estimated == pytest.approx(360.0)
    assert item.protein_g_estimated == pytest.approx(18.0)
    # Identity + log event + portion + timeline slot preserved.
    assert item.id == item_id
    assert item.log_event_id == log_event_id
    assert item.amount == pytest.approx(2.0)
    assert item.status == DerivedItemStatus.RESOLVED

    # Evidence rewritten in place to the applied source (still one row).
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert len(evidence) == 1
    assert evidence[0].source_type == "product_database"
    assert evidence[0].source_ref == "open_food_facts:0123456789012"
    assert evidence[0].content_hash == "hash-exact"
    assert evidence[0].basis == "per_100g"
    assert evidence[0].calories_per_100g == pytest.approx(120.0)
    assert evidence[0].product_id is None
    assert evidence[0].assumptions is None
    assert evidence[0].field_provenance is None

    # Exactly one re_match audit row (keyed on calories), no user_edit; is_edited false.
    rows = session.scalars(
        select(Correction).where(Correction.derived_food_item_id == item_id)
    ).all()
    assert [(r.source, r.field) for r in rows] == [(CorrectionSource.RE_MATCH, "calories")]
    assert rows[0].old_value == pytest.approx(300.0)
    assert rows[0].new_value == pytest.approx(360.0)
    assert item_read_model.item_is_edited(session, CandidateType.FOOD, item_id) is False


def test_exact_apply_creates_evidence_row_when_none_exists(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    # A low-trust item may have no prior evidence row; apply creates one defensively.
    user_id, _auth = register(client, "ee-noevidence@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=1.0, calories=200.0)

    proposal = _exact_proposal(uuid.UUID(user_id), item_id)
    _capability(session).apply(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        proposal_ref=encode_proposal_ref(proposal, SECRET),
    )

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert len(evidence) == 1
    assert evidence[0].source_type == "product_database"


# ---------------------------------------------------------------------------
# (c) Amount preservation + adjustment
# ---------------------------------------------------------------------------


def test_current_amount_is_preserved_by_default(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-amount-default@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)

    item = _capability(session).apply(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        proposal_ref=encode_proposal_ref(_exact_proposal(uuid.UUID(user_id), item_id), SECRET),
    )

    assert item.amount == pytest.approx(2.0)
    assert item.calories == pytest.approx(360.0)  # 2 × 150 g × 1.2


def test_amount_adjustment_costs_at_the_adjusted_amount_without_a_separate_row(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-amount-adjust@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)

    item = _capability(session).apply(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        proposal_ref=encode_proposal_ref(_exact_proposal(uuid.UUID(user_id), item_id), SECRET),
        amount=3.0,
    )

    # Adjusted before costing: 3 × 150 g = 450 g → ×4.5 of per-100g facts.
    assert item.amount == pytest.approx(3.0)
    assert item.calories == pytest.approx(540.0)
    # The adjustment is folded into the one re_match row — never a separate amount_adjust.
    rows = session.scalars(
        select(Correction).where(Correction.derived_food_item_id == item_id)
    ).all()
    assert [r.source for r in rows] == [CorrectionSource.RE_MATCH]
    assert (
        session.scalars(
            select(Correction).where(
                Correction.derived_food_item_id == item_id,
                Correction.source == CorrectionSource.AMOUNT_ADJUST,
            )
        ).all()
        == []
    )


def test_uncostable_amount_fails_closed_with_no_mutation(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    # A count quantity (2 servings) with a proposal that has no serving size cannot cost.
    user_id, _auth = register(client, "ee-uncostable@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    proposal = _exact_proposal(uuid.UUID(user_id), item_id, default_serving_g=None)

    with pytest.raises(AmountNotCostable):
        _capability(session).apply(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            proposal_ref=encode_proposal_ref(proposal, SECRET),
        )

    session.expire_all()
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    assert item.calories == pytest.approx(300.0)  # no fabricated number, no mutation
    assert (
        session.scalars(select(Correction).where(Correction.derived_food_item_id == item_id)).all()
        == []
    )


# ---------------------------------------------------------------------------
# (d) Fallback stays visibly low-trust
# ---------------------------------------------------------------------------


def test_fallback_apply_preserves_low_trust_provenance_and_assumptions(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-fallback@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    proposal = _fallback_proposal(
        uuid.UUID(user_id),
        item_id,
        source_type=SourceType.REFERENCE_SOURCE.value,
        assumptions=["barcode_no_match", "reference_page"],
    )

    _capability(session).apply(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        proposal_ref=encode_proposal_ref(proposal, SECRET),
    )

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).one()
    # Honest low-trust source + rough assumptions — never product_database / user_label.
    assert evidence.source_type == "reference_source"
    assert evidence.source_type not in {"product_database", "user_label"}
    assert evidence.assumptions == ["barcode_no_match", "reference_page"]

    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    descriptor = item_read_model.build_item_source(session, item)
    assert descriptor is not None
    assert descriptor.source_type is SourceType.REFERENCE_SOURCE


def test_fallback_model_prior_reads_as_rough_estimate(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-fallback-mp@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    proposal = _fallback_proposal(
        uuid.UUID(user_id),
        item_id,
        source_type=SourceType.MODEL_PRIOR.value,
        source_ref="model_prior",
        assumptions=["barcode_no_match", "model_prior_estimate"],
    )

    item = _capability(session).apply(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        proposal_ref=encode_proposal_ref(proposal, SECRET),
    )

    descriptor = item_read_model.build_item_source(session, item)
    assert descriptor is not None
    assert descriptor.source_type is SourceType.MODEL_PRIOR
    assert descriptor.label == "Rough estimate"


# ---------------------------------------------------------------------------
# (e) Proposal-reference rejection (no mutation)
# ---------------------------------------------------------------------------


def test_wrong_item_reference_is_rejected(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-wrong-item@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)
    # A validly signed proposal bound to a DIFFERENT item id.
    proposal = _exact_proposal(uuid.UUID(user_id), uuid.uuid4())

    with pytest.raises(ProposalNotResolvable):
        _capability(session).apply(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            proposal_ref=encode_proposal_ref(proposal, SECRET),
        )
    session.expire_all()
    assert session.get(DerivedFoodItem, item_id).calories == pytest.approx(300.0)  # type: ignore[union-attr]


def test_wrong_user_reference_is_rejected(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-wrong-user@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)
    # A validly signed proposal bound to a DIFFERENT owner but this item id.
    proposal = _exact_proposal(uuid.uuid4(), item_id)

    with pytest.raises(ProposalNotResolvable):
        _capability(session).apply(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            proposal_ref=encode_proposal_ref(proposal, SECRET),
        )
    session.expire_all()
    assert session.get(DerivedFoodItem, item_id).calories == pytest.approx(300.0)  # type: ignore[union-attr]


def test_tampered_reference_apply_is_rejected(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-tampered-apply@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)
    ref = encode_proposal_ref(_exact_proposal(uuid.UUID(user_id), item_id), SECRET)
    payload_b64, signature = ref.split(".")
    tampered = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B") + "." + signature

    with pytest.raises(ProposalNotResolvable):
        _capability(session).apply(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            proposal_ref=tampered,
        )
    session.expire_all()
    assert session.get(DerivedFoodItem, item_id).calories == pytest.approx(300.0)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# (e2) Quality/source-type semantics enforced at apply (no mutation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "high_trust_source",
    [SourceType.PRODUCT_DATABASE.value, SourceType.USER_LABEL.value],
)
def test_fallback_claiming_a_high_trust_source_is_rejected_no_mutation(
    client: TestClient, db_engine: Engine, session: Session, high_trust_source: str
) -> None:
    # A signed FALLBACK proposal that carries an exact/high-trust source_type must be
    # refused before any mutation — it can never be persisted as product_database /
    # user_label and read as exact (FTY-306/307 invariant).
    user_id, _auth = register(client, f"ee-fb-hitrust-{high_trust_source}@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    proposal = _fallback_proposal(uuid.UUID(user_id), item_id, source_type=high_trust_source)

    with pytest.raises(ProposalNotResolvable):
        _capability(session).apply(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            proposal_ref=encode_proposal_ref(proposal, SECRET),
        )

    session.expire_all()
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    assert item.calories == pytest.approx(300.0)  # no mutation
    # The item keeps whatever evidence it had — no product_database/user_label written.
    written = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
    ).all()
    assert all(e.source_type not in {"product_database", "user_label"} for e in written)
    assert (
        session.scalars(select(Correction).where(Correction.derived_food_item_id == item_id)).all()
        == []
    )


@pytest.mark.parametrize(
    ("kind", "wrong_source"),
    [
        # Barcode EXACT must be product_database, not a low-trust or label source.
        (ExactEvidenceKind.BARCODE, SourceType.REFERENCE_SOURCE.value),
        (ExactEvidenceKind.BARCODE, SourceType.USER_LABEL.value),
        # Label EXACT must be user_label, not product_database.
        (ExactEvidenceKind.LABEL, SourceType.PRODUCT_DATABASE.value),
    ],
)
def test_exact_proposal_with_mismatched_source_type_is_rejected_no_mutation(
    client: TestClient,
    db_engine: Engine,
    session: Session,
    kind: ExactEvidenceKind,
    wrong_source: str,
) -> None:
    user_id, _auth = register(client, f"ee-exact-mismatch-{kind.value}-{wrong_source}@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    proposal = _exact_proposal(uuid.UUID(user_id), item_id, kind=kind, source_type=wrong_source)

    with pytest.raises(ProposalNotResolvable):
        _capability(session).apply(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            proposal_ref=encode_proposal_ref(proposal, SECRET),
        )

    session.expire_all()
    assert session.get(DerivedFoodItem, item_id).calories == pytest.approx(300.0)  # type: ignore[union-attr]


def test_quality_none_proposal_is_not_applyable_no_mutation(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    # A quality=none proposal is a failure read with nothing to apply.
    user_id, _auth = register(client, "ee-quality-none@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    proposal = build_proposal(
        owner_id=uuid.UUID(user_id),
        item_id=item_id,
        kind=ExactEvidenceKind.BARCODE,
        quality=ExactEvidenceQuality.NONE,
        source_type=SourceType.MODEL_PRIOR.value,
        source_ref="model_prior",
        content_hash="hash-none",
        facts=_facts(),
    )

    with pytest.raises(ProposalNotResolvable):
        _capability(session).apply(
            owner_id=uuid.UUID(user_id),
            current_user=_user(session, user_id),
            item_id=item_id,
            proposal_ref=encode_proposal_ref(proposal, SECRET),
        )

    session.expire_all()
    assert session.get(DerivedFoodItem, item_id).calories == pytest.approx(300.0)  # type: ignore[union-attr]
    assert (
        session.scalars(select(Correction).where(Correction.derived_food_item_id == item_id)).all()
        == []
    )


# ---------------------------------------------------------------------------
# (f) Edit interaction
# ---------------------------------------------------------------------------


def test_apply_supersedes_a_pre_existing_user_edit(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-supersede@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    session.add(
        Correction(
            user_id=uuid.UUID(user_id),
            item_type=CandidateType.FOOD,
            derived_food_item_id=item_id,
            field="calories",
            old_value=300.0,
            new_value=250.0,
            source=CorrectionSource.USER_EDIT,
        )
    )
    session.commit()
    assert item_read_model.item_is_edited(session, CandidateType.FOOD, item_id) is True

    _capability(session).apply(
        owner_id=uuid.UUID(user_id),
        current_user=_user(session, user_id),
        item_id=item_id,
        proposal_ref=encode_proposal_ref(_exact_proposal(uuid.UUID(user_id), item_id), SECRET),
    )

    session.expire_all()
    # The applied source is the latest word: the stale edit is superseded.
    assert item_read_model.item_is_edited(session, CandidateType.FOOD, item_id) is False


# ---------------------------------------------------------------------------
# (g) Preview projection (serialize_proposal) — foundation for FTY-308/309
# ---------------------------------------------------------------------------


def test_serialize_exact_proposal_costs_preview_at_current_amount(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-preview-exact@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    proposal = _exact_proposal(uuid.UUID(user_id), item_id)

    dto = serialize_proposal(item, proposal, "ref-token")

    assert dto.proposal_ref == "ref-token"
    assert dto.kind is ExactEvidenceKind.BARCODE
    assert dto.quality is ExactEvidenceQuality.EXACT
    assert dto.failure_reason is None
    assert dto.can_cost_current_amount is True
    assert dto.preview is not None
    assert dto.preview.source.source_type is SourceType.PRODUCT_DATABASE
    assert dto.preview.calories == pytest.approx(360.0)  # costed at current 2 servings
    assert dto.preview.amount == pytest.approx(2.0)


def test_serialize_uncostable_proposal_carries_source_facts_and_flag(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-preview-uncostable@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    proposal = _exact_proposal(uuid.UUID(user_id), item_id, default_serving_g=None)

    dto = serialize_proposal(item, proposal, "ref-token")

    assert dto.can_cost_current_amount is False
    assert dto.preview is not None
    # Uncostable → the preview carries the proposal's per-100g source facts, not totals.
    assert dto.preview.calories == pytest.approx(120.0)
    assert dto.preview.basis == "per_100g"


def test_serialize_fallback_proposal_previews_rough_source(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    user_id, _auth = register(client, "ee-preview-fallback@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    item = session.get(DerivedFoodItem, item_id)
    assert item is not None
    proposal = _fallback_proposal(
        uuid.UUID(user_id),
        item_id,
        source_type=SourceType.MODEL_PRIOR.value,
        source_ref="model_prior",
    )

    dto = serialize_proposal(item, proposal, "ref-token", failure_reason="barcode_no_match")

    assert dto.quality is ExactEvidenceQuality.FALLBACK
    assert dto.failure_reason == "barcode_no_match"
    assert dto.preview is not None
    # Never presented as exact: the rough source label is what the applied item shows.
    assert dto.preview.source.source_type is SourceType.MODEL_PRIOR
    assert dto.preview.source.source_type not in {
        SourceType.PRODUCT_DATABASE,
        SourceType.USER_LABEL,
    }

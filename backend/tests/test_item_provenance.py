"""Per-item provenance read-model + provenance-preserving amount adjust (FTY-092).

Covers the two halves of the story against a migrated database:

1. the per-item ``source`` descriptor + ``is_edited`` flag the Today read-model
   exposes (the three ``is_edited`` cases, the source-type → label/ref mapping, the
   model-prior rough-estimate descriptor, and the defensive null source); and
2. the provenance-preserving amount adjust — a ``quantity`` edit rescales the
   numbers, tags its rows ``amount_adjust``, leaves the ``evidence_sources`` snapshot
   untouched, and keeps the item un-edited — contrasted with a value override that
   marks the item edited.
"""

from __future__ import annotations

import uuid
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import (
    ESTIMATE_BASIS_ASSUMPTION_PREFIX,
    CandidateType,
    CorrectionSource,
    MacroEstimateBasis,
    SourceType,
)
from app.models.corrections import Correction
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.schemas.corrections import DerivedExerciseItemDTO, DerivedFoodItemDTO
from app.services import item_read_model
from tests.corrections_helpers import (
    register,
    seed_evidence,
    seed_exercise_item,
    seed_food_item,
)

_USDA_REF = "usda_fdc:168880"


def _seed_usda(db_engine: Engine, user_id: str, item_id: uuid.UUID) -> None:
    """Attach a USDA evidence record to a seeded food item."""

    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type=SourceType.TRUSTED_NUTRITION_DATABASE,
        source_ref=_USDA_REF,
    )


def _read_food(db_engine: Engine, item_id: uuid.UUID) -> DerivedFoodItemDTO:
    """Serialize a food item through the shared read-model serializer."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        return item_read_model.serialize_food_item(session, item)


def _read_exercise(db_engine: Engine, item_id: uuid.UUID) -> DerivedExerciseItemDTO:
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedExerciseItem, item_id)
        assert item is not None
        return item_read_model.serialize_exercise_item(session, item)


def _patch(
    client: TestClient,
    user_id: str,
    item_type: str,
    item_id: uuid.UUID,
    auth: str,
    body: dict[str, object],
) -> httpx.Response:
    return cast(
        httpx.Response,
        client.patch(
            f"/api/users/{user_id}/derived-items/{item_type}/{item_id}",
            headers={"Authorization": auth},
            json=body,
        ),
    )


# --------------------------------------------------------------------------- #
# is_edited derivation — the three load-bearing cases
# --------------------------------------------------------------------------- #


def test_never_edited_item_is_not_edited(client: TestClient, db_engine: Engine) -> None:
    user_id, _ = register(client, "prov-never@example.com")
    item_id = seed_food_item(db_engine, user_id)
    _seed_usda(db_engine, user_id, item_id)

    dto = _read_food(db_engine, item_id)

    assert dto.is_edited is False
    assert dto.source is not None
    assert dto.source.source_type is SourceType.TRUSTED_NUTRITION_DATABASE


def test_amount_adjusted_only_item_is_not_edited(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "prov-amount@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=1.0)
    _seed_usda(db_engine, user_id, item_id)

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "quantity", "value": 2})
    assert resp.status_code == 200

    dto = _read_food(db_engine, item_id)
    assert dto.is_edited is False


def test_value_override_marks_item_edited(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "prov-override@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)
    _seed_usda(db_engine, user_id, item_id)

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "calories", "value": 180})
    assert resp.status_code == 200

    dto = _read_food(db_engine, item_id)
    assert dto.is_edited is True
    # Provenance is unchanged by a value override — the source icon stays.
    assert dto.source is not None
    assert dto.source.source_type is SourceType.TRUSTED_NUTRITION_DATABASE


# --------------------------------------------------------------------------- #
# Amount adjust preserves provenance; value override does not change the amount
# --------------------------------------------------------------------------- #


def test_amount_adjust_preserves_provenance(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "prov-preserve@example.com")
    item_id = seed_food_item(
        db_engine, user_id, amount=2.0, calories=300.0, protein_g=10.0, carbs_g=40.0, fat_g=5.0
    )
    _seed_usda(db_engine, user_id, item_id)

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "quantity", "value": 3})
    assert resp.status_code == 200
    body = resp.json()

    # Rescaled values (ratio 1.5), un-edited, and the source descriptor preserved.
    assert (body["calories"], body["protein_g"], body["carbs_g"], body["fat_g"]) == (
        450.0,
        15.0,
        60.0,
        7.5,
    )
    assert body["is_edited"] is False
    assert body["source"] == {
        "source_type": "trusted_nutrition_database",
        "label": "USDA",
        "ref": _USDA_REF,
        # A USDA source is not a user_text comparable-reference estimate.
        "estimate_basis": None,
    }

    factory = create_session_factory(db_engine)
    with factory() as session:
        rows = list(
            session.scalars(select(Correction).where(Correction.derived_food_item_id == item_id))
        )
        # Every rescale row (quantity + each macro) is tagged amount_adjust, never user_edit.
        assert {r.field for r in rows} == {"quantity", "calories", "protein_g", "carbs_g", "fat_g"}
        assert {r.source for r in rows} == {CorrectionSource.AMOUNT_ADJUST}

        # The evidence/source snapshot is untouched by a portion fix.
        evidence = session.scalars(
            select(EvidenceSource).where(EvidenceSource.derived_food_item_id == item_id)
        ).one()
        assert evidence.source_type == SourceType.TRUSTED_NUTRITION_DATABASE
        assert evidence.source_ref == _USDA_REF


def test_value_override_appends_single_user_edit_row_without_touching_amount(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "prov-single@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    _seed_usda(db_engine, user_id, item_id)

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "calories", "value": 280})
    assert resp.status_code == 200
    body = resp.json()

    # Contrast with the amount-adjust case: edited, amount unchanged, one user_edit row.
    assert body["is_edited"] is True
    assert body["amount"] == 2.0

    factory = create_session_factory(db_engine)
    with factory() as session:
        rows = list(
            session.scalars(select(Correction).where(Correction.derived_food_item_id == item_id))
        )
        assert len(rows) == 1
        assert rows[0].field == "calories"
        assert rows[0].source == CorrectionSource.USER_EDIT


# --------------------------------------------------------------------------- #
# Source descriptor mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source_type", "source_ref", "expected_label"),
    [
        (SourceType.TRUSTED_NUTRITION_DATABASE, "usda_fdc:171688", "USDA"),
        (SourceType.PRODUCT_DATABASE, "open_food_facts:0123456789012", "Open Food Facts"),
        (SourceType.USER_LABEL, "user_label:deadbeef", "Label scan"),
        (
            SourceType.OFFICIAL_SOURCE,
            "official_source:https://nutrition.example.com/menu/item",
            "nutrition.example.com",
        ),
        (
            SourceType.REFERENCE_SOURCE,
            "reference_source:https://en.wikipedia.org/wiki/Banana",
            "en.wikipedia.org",
        ),
        # Unparsable ref URL falls back to the generic per-tier label.
        (SourceType.REFERENCE_SOURCE, "reference_source:not a url", "Reference source"),
        (SourceType.MODEL_PRIOR, "model_prior", "Rough estimate"),
    ],
)
def test_source_descriptor_maps_type_to_label_and_ref(
    client: TestClient,
    db_engine: Engine,
    source_type: SourceType,
    source_ref: str,
    expected_label: str,
) -> None:
    user_id, _ = register(client, f"prov-map-{source_type.value}@example.com")
    item_id = seed_food_item(db_engine, user_id)
    seed_evidence(db_engine, user_id, item_id, source_type=source_type, source_ref=source_ref)

    dto = _read_food(db_engine, item_id)

    assert dto.source is not None
    assert dto.source.source_type is source_type
    assert dto.source.label == expected_label
    assert dto.source.ref == source_ref


def test_model_prior_item_surfaces_rough_estimate_descriptor(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, _ = register(client, "prov-rough@example.com")
    item_id = seed_food_item(db_engine, user_id)
    seed_evidence(
        db_engine, user_id, item_id, source_type=SourceType.MODEL_PRIOR, source_ref="model_prior"
    )

    dto = _read_food(db_engine, item_id)

    # The descriptor alone distinguishes a rough estimate from a sourced match.
    assert dto.source is not None
    assert dto.source.source_type is SourceType.MODEL_PRIOR
    assert dto.source.label == "Rough estimate"


def test_user_text_comparable_marker_surfaces_estimate_basis(
    client: TestClient, db_engine: Engine
) -> None:
    # A user_text evidence row carrying the code-emitted comparable-reference marker in its
    # assumptions surfaces the trusted rough-aggregate estimate_basis (FTY-281).
    user_id, _ = register(client, "prov-basis@example.com")
    item_id = seed_food_item(db_engine, user_id)
    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type=SourceType.USER_TEXT,
        source_ref="user_text:" + "a" * 8,
        assumptions=[
            f"{ESTIMATE_BASIS_ASSUMPTION_PREFIX}{MacroEstimateBasis.COMPARABLE_REFERENCE.value}",
            "protein_g estimated from a rough comparable-reference aggregate",
        ],
    )

    dto = _read_food(db_engine, item_id)

    assert dto.source is not None
    assert dto.source.source_type is SourceType.USER_TEXT
    assert dto.source.estimate_basis is MacroEstimateBasis.COMPARABLE_REFERENCE


def test_provider_assumption_mimicking_marker_on_model_prior_is_not_a_basis(
    client: TestClient, db_engine: Engine
) -> None:
    # The estimate_basis derivation is a *trusted* signal keyed on source_type == user_text.
    # A non-aggregate tier (model_prior) persists provider-generated free-form assumptions;
    # even one that mimics the marker text must never be read as a comparable-reference basis.
    user_id, _ = register(client, "prov-spoof@example.com")
    item_id = seed_food_item(db_engine, user_id)
    seed_evidence(
        db_engine,
        user_id,
        item_id,
        source_type=SourceType.MODEL_PRIOR,
        source_ref="model_prior",
        assumptions=[
            f"{ESTIMATE_BASIS_ASSUMPTION_PREFIX}{MacroEstimateBasis.COMPARABLE_REFERENCE.value}",
        ],
    )

    dto = _read_food(db_engine, item_id)

    assert dto.source is not None
    assert dto.source.source_type is SourceType.MODEL_PRIOR
    assert dto.source.estimate_basis is None


def test_missing_evidence_yields_null_source_defensively(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, _ = register(client, "prov-null@example.com")
    item_id = seed_food_item(db_engine, user_id)  # no evidence_sources row

    dto = _read_food(db_engine, item_id)

    assert dto.source is None
    assert dto.is_edited is False


# --------------------------------------------------------------------------- #
# Exercise items: no evidence source, same is_edited rule
# --------------------------------------------------------------------------- #


def test_exercise_item_has_null_source_and_edit_rule(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "prov-exercise@example.com")
    item_id = seed_exercise_item(db_engine, user_id, active_calories=120.0)

    before = _read_exercise(db_engine, item_id)
    assert before.source is None
    assert before.is_edited is False

    resp = _patch(
        client, user_id, "exercise", item_id, auth, {"field": "active_calories", "value": 150}
    )
    assert resp.status_code == 200
    assert resp.json()["is_edited"] is True

    after = _read_exercise(db_engine, item_id)
    assert after.is_edited is True


# --------------------------------------------------------------------------- #
# is_edited query helper directly (unit)
# --------------------------------------------------------------------------- #


def test_item_is_edited_ignores_amount_adjust_corrections(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "prov-helper@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=1.0, calories=200.0)

    def _do(field: str, value: float) -> None:
        resp = _patch(client, user_id, "food", item_id, auth, {"field": field, "value": value})
        assert resp.status_code == 200

    # Two amount adjusts leave the item un-edited; a later value override flips it.
    _do("quantity", 2)
    _do("quantity", 3)

    factory = create_session_factory(db_engine)
    with factory() as session:
        assert item_read_model.item_is_edited(session, CandidateType.FOOD, item_id) is False

    _do("calories", 99)

    factory = create_session_factory(db_engine)
    with factory() as session:
        assert item_read_model.item_is_edited(session, CandidateType.FOOD, item_id) is True

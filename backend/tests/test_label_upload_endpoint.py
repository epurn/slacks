"""HTTP nutrition-label upload endpoint (FTY-064).

Exercise ``POST /api/users/{user_id}/log-events/label`` across the trust boundary
against the migrated SQLite database. The label processor seam is replaced with a
double backed by a network-free :class:`FakeProvider`, so the endpoint resolves a
real (scripted) panel without a live model:

- happy path: a raw image body → a ``completed`` event whose extracted food row
  carries deterministic calories/macros;
- the ``save`` query flag drives FTY-077 retention (discard by default, one
  ``log_attachments`` row on an explicit save);
- the data trust boundary rejects a non-image body (``415``) and an oversized one
  (``413``) before any event is created;
- ownership fails closed (a cross-user upload is a ``404``; an unauthenticated one
  is a ``401``);
- the synchronous path never enqueues an estimation job (the image is never
  published to the broker).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.estimator.label_step import LabelInput, LabelResolveStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.attachments import LogAttachment
from app.models.derived import DerivedFoodItem
from app.schemas.attachments import MAX_ATTACHMENT_BYTES
from tests.conftest import RecordingEnqueuer

#: A minimal payload whose leading signature is a real PNG (matches the validator's
#: magic-number gate without being a full image).
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

#: The panel the scripted provider returns: 200 kcal / 10 P / 20 C / 8 F per 40 g.
_PANEL: dict[str, Any] = {
    "disposition": "extracted",
    "confidence": 0.95,
    "facts": {
        "product_name": "Trail Mix",
        "serving_size_amount": 40.0,
        "serving_size_unit": "g",
        "servings_per_container": 5.0,
        "energy_kcal_per_serving": 200.0,
        "protein_g_per_serving": 10.0,
        "carbs_g_per_serving": 20.0,
        "fat_g_per_serving": 8.0,
    },
}


def _install_scripted_processor(
    client: TestClient, responses: list[dict[str, Any]] | None = None
) -> None:
    """Replace the app's label processor with one backed by a scripted provider."""

    panels: list[dict[str, Any] | LLMError] = list(responses or [dict(_PANEL)])

    def processor(
        session: Session,
        *,
        log_event_id: uuid.UUID,
        user_id: uuid.UUID,
        label_upload: LabelInput,
    ) -> None:
        provider = FakeProvider(responses=panels, supports_vision=True)
        process_estimation(
            session,
            log_event_id=log_event_id,
            user_id=user_id,
            label_upload=label_upload,
            pipeline=Pipeline([LabelResolveStep(provider)]),
        )

    client.app.state.label_processor = processor  # type: ignore[attr-defined]


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _register(client: TestClient, email: str) -> tuple[uuid.UUID, str]:
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    return user_id, auth


def _upload(
    client: TestClient,
    user_id: uuid.UUID,
    auth: str,
    *,
    data: bytes = _PNG_BYTES,
    content_type: str = "image/png",
    save: bool | None = None,
) -> Any:
    params = {} if save is None else {"save": str(save).lower()}
    return client.post(
        f"/api/users/{user_id}/log-events/label",
        headers={"Authorization": auth, "Content-Type": content_type},
        params=params,
        content=data,
    )


def test_upload_resolves_to_a_completed_event_with_deterministic_facts(
    client: TestClient, session: Session
) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "label-upload-ok@example.com")

    response = _upload(client, user_id, auth)

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(user_id)
    assert body["status"] == LogEventStatus.COMPLETED.value
    event_id = uuid.UUID(body["id"])

    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id)
    ).one()
    assert food.name == "Trail Mix"
    assert food.user_id == user_id
    # Default consumed quantity is one 40 g serving → the printed per-serving values.
    assert food.calories == 200.0
    assert food.grams == 40.0


def test_default_upload_discards_the_raw_image(client: TestClient, session: Session) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "label-upload-discard@example.com")

    response = _upload(client, user_id, auth)  # save omitted → defaults off

    assert response.status_code == 201
    assert session.scalars(select(LogAttachment)).all() == []


def test_explicit_save_retains_one_attachment(client: TestClient, session: Session) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "label-upload-save@example.com")

    response = _upload(client, user_id, auth, save=True)

    assert response.status_code == 201
    attachments = list(session.scalars(select(LogAttachment)))
    assert len(attachments) == 1
    assert attachments[0].user_id == user_id
    assert attachments[0].content_type == "image/png"


def test_non_image_body_is_rejected_before_any_event(client: TestClient, session: Session) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "label-upload-bad@example.com")

    response = _upload(client, user_id, auth, data=b"not really a png", content_type="image/png")

    assert response.status_code == 415
    # Fail closed: no event, no food, no attachment created on an invalid upload.
    assert session.scalars(select(DerivedFoodItem)).all() == []
    assert session.scalars(select(LogAttachment)).all() == []


def test_disallowed_content_type_is_rejected(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "label-upload-type@example.com")

    response = _upload(client, user_id, auth, data=b"%PDF-1.4", content_type="application/pdf")

    assert response.status_code == 415


def test_oversized_upload_is_rejected(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "label-upload-big@example.com")
    oversized = _PNG_BYTES + b"\x00" * (MAX_ATTACHMENT_BYTES + 1)

    response = _upload(client, user_id, auth, data=oversized)

    assert response.status_code == 413


def test_upload_for_another_user_is_not_found(client: TestClient) -> None:
    _install_scripted_processor(client)
    _, auth = _register(client, "label-upload-owner@example.com")
    other_user_id = uuid.uuid4()

    response = _upload(client, other_user_id, auth)

    assert response.status_code == 404


def test_unauthenticated_upload_is_rejected(client: TestClient) -> None:
    _install_scripted_processor(client)
    user_id = uuid.uuid4()

    response = client.post(
        f"/api/users/{user_id}/log-events/label",
        headers={"Content-Type": "image/png"},
        content=_PNG_BYTES,
    )

    assert response.status_code == 401


def test_synchronous_upload_never_enqueues_a_job(
    client: TestClient, enqueuer: RecordingEnqueuer
) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "label-upload-noenqueue@example.com")

    response = _upload(client, user_id, auth)

    assert response.status_code == 201
    # The image is resolved in-request; nothing is published to the broker.
    assert enqueuer.calls == []

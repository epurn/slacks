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
  published to the broker);
- a transient (retryable) vision-provider blip is retried within a bounded in-request
  budget: it clears to the normal event when it recovers, else returns a retryable
  ``503`` with **nothing persisted** (FTY-390), while genuinely-not-a-label input still
  lands terminal ``failed`` and an unreadable panel still lands ``needs_clarification``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus
from app.estimator import label_upload, worker_pipeline
from app.estimator.label_step import LabelInput, LabelResolveStep
from app.estimator.label_upload import LABEL_MAX_ATTEMPTS
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.llm.errors import LLMError, LLMTransientError
from app.llm.providers.fake import FakeProvider
from app.models.attachments import LogAttachment
from app.models.derived import DerivedFoodItem
from app.models.estimation import EstimationJob
from app.models.food_sources import EvidenceSource
from app.models.log_events import LogEvent
from app.schemas.attachments import MAX_ATTACHMENT_BYTES
from tests.conftest import RecordingEnqueuer

#: A scripted panel the model marks as unreadable (recognisably a label, numbers not
#: legible) → the step routes to ``needs_clarification`` rather than guess.
_UNREADABLE: dict[str, Any] = {"disposition": "unreadable", "confidence": 0.9}

#: A scripted reply the model marks as not-a-label → the step fails closed (terminal
#: ``failed``); genuinely-not-a-label input is the one thing that still rejects.
_NOT_A_LABEL: dict[str, Any] = {
    "disposition": "not_a_label",
    "confidence": 0.95,
    "reason": "not a nutrition label",
}


def _drive_real_seam(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    responses: Sequence[dict[str, Any] | LLMError],
) -> FakeProvider:
    """Wire the production ``synchronous_label_processor`` to a scripted provider.

    Drives the real seam (installed by ``create_app``) — its bounded retry loop,
    backoff, and deadline — rather than the test double, but makes the vision provider
    it builds return ``responses`` in order and replaces its backoff sleep with a no-op
    so the retry path runs without real wall-clock waits (FTY-390). The same
    :class:`FakeProvider` instance backs every attempt, so its ``prompts`` count the
    per-request provider calls.
    """

    fake = FakeProvider(responses=list(responses), supports_vision=True)
    monkeypatch.setattr(worker_pipeline, "load_llm_settings", lambda: None)
    monkeypatch.setattr(worker_pipeline, "build_provider", lambda _settings: fake)
    monkeypatch.setattr(label_upload, "_sleep", lambda _s: None)
    return fake


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
    # FTY-196: the item lands as an uncounted *proposal* (the event still completes,
    # but the food does not count until the user confirms it).
    assert food.status == DerivedItemStatus.PROPOSED
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


def test_transient_then_success_within_budget_yields_completed(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient blip that clears within the retry budget yields the normal event.

    FTY-390: a retryable vision-provider failure followed by a legible read inside the
    bounded in-request budget resolves to the normal ``completed`` post-extraction event
    — no terminal ``failed``, no ``503`` — proven with a stubbed provider and a no-op
    backoff seam so the test runs without real waits.
    """

    fake = _drive_real_seam(client, monkeypatch, [LLMTransientError("boom"), dict(_PANEL)])
    user_id, auth = _register(client, "label-upload-transient-ok@example.com")

    response = _upload(client, user_id, auth)

    assert response.status_code == 201
    assert response.json()["status"] == LogEventStatus.COMPLETED.value
    # One retry: the provider was called exactly twice (transient, then success).
    assert len(fake.prompts) == 2
    food = session.scalars(select(DerivedFoodItem)).one()
    assert food.name == "Trail Mix"
    assert food.status == DerivedItemStatus.PROPOSED


def test_transient_exhaustion_returns_503_and_persists_nothing(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider that fails retryably through the whole budget → ``503``, nothing kept.

    FTY-390: when the transient budget is exhausted the request returns a retryable
    ``503`` and the database holds **no** log event, food item, evidence, or attachment
    row afterward — the client still holds the image and retries.
    """

    fake = _drive_real_seam(client, monkeypatch, [LLMTransientError("boom")] * LABEL_MAX_ATTEMPTS)
    user_id, auth = _register(client, "label-upload-exhausted@example.com")

    response = _upload(client, user_id, auth)

    assert response.status_code == 503
    # Bounded: never more provider calls than the documented attempt budget.
    assert len(fake.prompts) == LABEL_MAX_ATTEMPTS
    # Nothing persisted: no event, food, evidence, attachment, or estimation job.
    assert session.scalars(select(LogEvent)).all() == []
    assert session.scalars(select(DerivedFoodItem)).all() == []
    assert session.scalars(select(EvidenceSource)).all() == []
    assert session.scalars(select(LogAttachment)).all() == []
    assert session.scalars(select(EstimationJob)).all() == []


def test_transient_exhaustion_persists_nothing_even_with_save_true(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``save=true`` does not survive a transient exhaustion (FTY-390).

    Even when the user asked to keep the image, an exhausted transient failure returns
    ``503`` and retains no ``log_attachments`` row (retention short-circuits on a failed
    outcome, and the purge is unconditional), so nothing is persisted either way.
    """

    _drive_real_seam(client, monkeypatch, [LLMTransientError("boom")] * LABEL_MAX_ATTEMPTS)
    user_id, auth = _register(client, "label-upload-exhausted-save@example.com")

    response = _upload(client, user_id, auth, save=True)

    assert response.status_code == 503
    assert session.scalars(select(LogEvent)).all() == []
    assert session.scalars(select(LogAttachment)).all() == []


def test_retry_after_503_creates_exactly_one_event(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client retry after a ``503`` that then succeeds leaves exactly one event.

    FTY-390: because the exhausted first upload persisted nothing, the successful retry
    creates the *only* event — no duplicate, no orphaned ``failed`` entry. The shared
    scripted provider fails through the first upload's budget, then reads legibly on the
    retry.
    """

    _drive_real_seam(
        client,
        monkeypatch,
        [LLMTransientError("boom")] * LABEL_MAX_ATTEMPTS + [dict(_PANEL)],
    )
    user_id, auth = _register(client, "label-upload-retry@example.com")

    first = _upload(client, user_id, auth)
    assert first.status_code == 503

    second = _upload(client, user_id, auth)
    assert second.status_code == 201
    assert second.json()["status"] == LogEventStatus.COMPLETED.value

    # Exactly one event survives: the first upload left nothing behind.
    assert len(session.scalars(select(LogEvent)).all()) == 1


def test_503_body_is_content_free(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``503`` body carries only a fixed action description, no leaked content.

    FTY-390 security posture: the retryable ``503`` never echoes image bytes, extracted
    text, provider output, or stack detail — only a content-free message family.
    """

    _drive_real_seam(client, monkeypatch, [LLMTransientError("boom")] * LABEL_MAX_ATTEMPTS)
    user_id, auth = _register(client, "label-upload-redaction@example.com")

    response = _upload(client, user_id, auth)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail == "label extraction is temporarily unavailable"
    # No image bytes / provider message / extracted panel content leaks into the body.
    assert "boom" not in response.text
    assert "Trail Mix" not in response.text


def test_not_a_label_still_lands_terminal_failed(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Genuinely-not-a-label input still fails closed as terminal ``failed`` (FTY-370).

    The never-reject change is scoped to *transient* provider errors: a deterministic
    not-a-label reply is not retried and lands terminal ``failed`` on the first attempt,
    unchanged — proving ``503`` did not swallow the honest rejection.
    """

    fake = _drive_real_seam(client, monkeypatch, [dict(_NOT_A_LABEL)])
    user_id, auth = _register(client, "label-upload-notlabel@example.com")

    response = _upload(client, user_id, auth)

    assert response.status_code == 201
    assert response.json()["status"] == LogEventStatus.FAILED.value
    # Deterministic: one call, no retry, no food derived.
    assert len(fake.prompts) == 1
    assert session.scalars(select(DerivedFoodItem)).all() == []


def test_unreadable_panel_still_lands_needs_clarification(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable panel still lands ``needs_clarification``, unchanged (FTY-390).

    An unreadable read is a deterministic outcome, not a transient error, so it is not
    retried and reaches the ``needs_clarification`` terminal status as before.
    """

    fake = _drive_real_seam(client, monkeypatch, [dict(_UNREADABLE)])
    user_id, auth = _register(client, "label-upload-unreadable@example.com")

    response = _upload(client, user_id, auth)

    assert response.status_code == 201
    assert response.json()["status"] == LogEventStatus.NEEDS_CLARIFICATION.value
    assert len(fake.prompts) == 1


def test_synchronous_upload_never_enqueues_a_job(
    client: TestClient, enqueuer: RecordingEnqueuer
) -> None:
    _install_scripted_processor(client)
    user_id, auth = _register(client, "label-upload-noenqueue@example.com")

    response = _upload(client, user_id, auth)

    assert response.status_code == 201
    # The image is resolved in-request; nothing is published to the broker.
    assert enqueuer.calls == []

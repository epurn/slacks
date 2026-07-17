"""Estimator consumption of mixed text+image events (FTY-376).

Drives :func:`app.estimator.processing.process_estimation` over events created
with transient image attachments (the FTY-375 seam), proving the
``estimation-jobs.md`` v6 / ``parse-candidates.md`` v12 rules:

- **Pipeline selection:** an image-bearing NL event runs the text-parse /
  interpretation pipeline with the images attached as vision evidence — never
  the label-only ``label_pipeline`` (reserved for the synchronous label
  endpoint's ``label_upload`` path).
- **Worker-side image load, ids-only payload:** the job payload stays
  ``{log_event_id, user_id}``; the worker reaches the images through the
  database by event id.
- **The worked mixed case:** ``"2 of these bars"`` + a label photo resolves
  with the amount from the text surface and ``user_label`` facts from the
  image, scaled deterministically, with the image ``content_hash`` on the
  evidence row.
- **Text-only regression:** an event without images estimates exactly as
  today — same prompt, no image ever passed to the provider.
- **Estimate-first degradation:** a transient provider error retries (the event
  honestly stays ``processing``); an unusable image or a provider failure on
  the label read degrades to the ordinary tiers; a non-vision deployment
  degrades to text-only estimation, and an image-only event on one routes to a
  clarifying question — never a terminal rejection.
- **Terminal purge + redaction:** transient images are purged in the terminal
  transaction on the event-terminal statuses (``completed`` / every ``failed``
  flavour), retained across the awaiting-answer clarify window
  (``log-attachments.md`` v3), saved rows always survive, and no image
  bytes/hashes appear in the run ``trace``/``error`` or logs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import (
    DerivedItemStatus,
    EstimationJobStatus,
    EstimationRunStatus,
    LogEventStatus,
)
from app.estimator.event_images import (
    IMAGE_EVIDENCE_UNAVAILABLE_ASSUMPTION,
    PHOTO_ONLY_MARKER_TEXT,
    PHOTO_WITHOUT_VISION_QUESTION,
    EventImage,
    load_event_images,
)
from app.estimator.image_facts_step import (
    AMOUNT_FROM_TEXT_ASSUMPTION,
    ImageFactsResolveStep,
)
from app.estimator.label_step import (
    LABEL_EXTRACTION_PROMPT,
    USER_LABEL_SOURCE_TYPE,
    LabelInput,
)
from app.estimator.parse import ParseStep
from app.estimator.parse_prompt import build_parse_prompt
from app.estimator.pipeline import (
    CandidateDraft,
    ClarificationDraft,
    EstimationContext,
    NeedsClarification,
    Pipeline,
    StepError,
    StepFailed,
    StubCalculateStep,
    StubParseStep,
)
from app.estimator.processing import process_estimation
from app.estimator.run_budget import WALL_CLOCK_DEADLINE_EXCEEDED
from app.estimator.worker_pipeline import build_worker_pipeline
from app.llm.base import ImageInput, Provider
from app.llm.errors import LLMTransientError
from app.models.attachments import LogAttachment
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource
from app.models.identity import User
from app.models.log_events import LogEvent
from app.routers.log_event_multipart import PHOTO_LOG_EVENT_RAW_TEXT
from app.schemas.estimation import EstimationJobPayload
from app.services.attachments import ValidatedImage, stage_submission_images

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_PNG_IMAGE = ValidatedImage(data=_PNG_BYTES, content_type="image/png")
#: A second, byte-distinct image so multi-image tests can tell the surfaces
#: apart by ``content_hash`` and script per-image panel replies.
_PNG_BYTES_2 = b"\x89PNG\r\n\x1a\n" + b"\x01" * 16
_PNG_IMAGE_2 = ValidatedImage(data=_PNG_BYTES_2, content_type="image/png")

#: A stable parse reply for the worked case: the text surface states the count.
_PARSE_PAYLOAD: dict[str, Any] = {
    "disposition": "parsed",
    "confidence": 0.95,
    "items": [
        {
            "type": "food",
            "name": "protein bar",
            "quantity_text": "2",
            "unit": "bars",
            "amount": 2,
        }
    ],
    "clarification_questions": [],
}

#: A legible label panel: 40 g serving, 200 kcal / 10 P / 20 C / 8 F per serving
#: → per-100g 500 / 25 / 50 / 20.
_PANEL_PAYLOAD: dict[str, Any] = {
    "disposition": "extracted",
    "confidence": 0.95,
    "facts": {
        "product_name": "Protein bar",
        "serving_size_amount": 40,
        "serving_size_unit": "g",
        "energy_kcal_per_serving": 200,
        "protein_g_per_serving": 10,
        "carbs_g_per_serving": 20,
        "fat_g_per_serving": 8,
    },
}

#: A legible panel for an entirely different product than any text candidate in
#: the mis-attribution tests: 50 g serving → per-100g 440 / 10 / 70 / 14.
_GRANOLA_PANEL_PAYLOAD: dict[str, Any] = {
    "disposition": "extracted",
    "confidence": 0.95,
    "facts": {
        "product_name": "Granola crunch",
        "serving_size_amount": 50,
        "serving_size_unit": "g",
        "energy_kcal_per_serving": 220,
        "protein_g_per_serving": 5,
        "carbs_g_per_serving": 35,
        "fat_g_per_serving": 7,
    },
}


class _ScriptedVisionProvider(Provider):
    """Routes parse-prompt calls and label-extraction calls to scripted payloads.

    Prompt-shape routing (rather than call order) keeps the script stable under
    the parallel self-consistency sampler, and ``panel_payloads`` routes label
    replies by the received image *bytes* so multi-image scripts stay stable
    under the loader's row ordering. Records per-call image counts so tests can
    assert exactly which calls carried the vision surfaces.
    """

    name = "fake"

    def __init__(
        self,
        *,
        parse_payload: dict[str, Any] | None = None,
        panel_payload: dict[str, Any] | None = None,
        panel_payloads: dict[bytes, dict[str, Any]] | None = None,
        parse_error: Exception | None = None,
        panel_error: Exception | None = None,
        supports_vision: bool = True,
    ) -> None:
        super().__init__(timeout_seconds=1.0, max_retries=0, supports_vision=supports_vision)
        self._parse_payload = parse_payload or _PARSE_PAYLOAD
        self._panel_payload = panel_payload or _PANEL_PAYLOAD
        self._panel_payloads = panel_payloads
        self._parse_error = parse_error
        self._panel_error = panel_error
        self.parse_prompts: list[str] = []
        self.parse_image_counts: list[int] = []
        self.panel_image_counts: list[int] = []

    def _complete(
        self,
        prompt: str,
        schema: Any,
        *,
        images: Any,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        count = len(images) if images else 0
        if prompt == LABEL_EXTRACTION_PROMPT:
            self.panel_image_counts.append(count)
            if self._panel_error is not None:
                raise self._panel_error
            if self._panel_payloads is not None:
                return dict(self._panel_payloads[images[0].data])
            return dict(self._panel_payload)
        self.parse_prompts.append(prompt)
        self.parse_image_counts.append(count)
        if self._parse_error is not None:
            raise self._parse_error
        return dict(self._parse_payload)


def _vision_pipeline(provider: Provider) -> Pipeline:
    """The parse + image-facts slice of the mixed pipeline under test."""

    return Pipeline([ParseStep(provider), ImageFactsResolveStep(provider)])


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


@pytest.fixture
def user(session: Session) -> User:
    row = User()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _seed_image_event(
    session: Session,
    user: User,
    raw_text: str = "2 of these bars",
    *,
    images: int | list[ValidatedImage] = 1,
    save: bool = False,
) -> LogEvent:
    """A ``pending`` event with staged FTY-375 transient (or saved) images.

    ``images`` is a count of identical placeholder images, or an explicit list
    when a test needs byte-distinct surfaces.
    """

    event = LogEvent(user_id=user.id, raw_text=raw_text, status=LogEventStatus.PENDING)
    session.add(event)
    session.flush()
    payloads = [_PNG_IMAGE] * images if isinstance(images, int) else images
    if payloads:
        stage_submission_images(
            session,
            owner_id=user.id,
            current_user=user,
            log_event_id=event.id,
            images=payloads,
            save=save,
        )
    session.commit()
    session.refresh(event)
    return event


def _attachments_for(session: Session, event_id: uuid.UUID) -> list[LogAttachment]:
    return list(
        session.scalars(select(LogAttachment).where(LogAttachment.log_event_id == event_id)).all()
    )


def _run_for(session: Session, event_id: uuid.UUID) -> EstimationRun:
    runs = list(
        session.scalars(select(EstimationRun).where(EstimationRun.log_event_id == event_id))
    )
    assert runs, "expected an estimation run"
    return runs[-1]


# ---------------------------------------------------------------------------
# Pipeline selection + ids-only payload
# ---------------------------------------------------------------------------


def test_selection_rule_image_bearing_event_runs_parse_pipeline_not_label_pipeline(
    session: Session,
) -> None:
    """The selection rule (``estimation-jobs.md`` v6): only a synchronous label
    upload (``label_upload`` present) selects ``label_pipeline``; every other
    event — image-bearing unified submissions included — runs the text-parse /
    interpretation pipeline with the image-facts step wired in."""

    nl_steps = [step.name for step in build_worker_pipeline(session, None).steps]
    assert "parse" in nl_steps
    assert "image_facts_resolve" in nl_steps
    assert "label_resolve" not in nl_steps

    label = LabelInput(data=_PNG_BYTES, content_type="image/png")
    label_steps = [step.name for step in build_worker_pipeline(session, label).steps]
    assert label_steps == ["label_resolve"]


def test_job_payload_is_ids_only() -> None:
    """The FTY-374 reaffirmed payload shape: ids only, nothing else admissible."""

    assert set(EstimationJobPayload.model_fields) == {"log_event_id", "user_id"}
    with pytest.raises(Exception, match="extra"):
        EstimationJobPayload.model_validate(
            {"log_event_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4()), "image": "x"}
        )


# ---------------------------------------------------------------------------
# The worked mixed case: text count × image label facts, per-surface provenance
# ---------------------------------------------------------------------------


def test_worked_case_text_count_scales_image_label_facts(
    session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("SLACKS_LLM_SUPPORTS_VISION", "true")
    event = _seed_image_event(session, user)
    content_hash = _attachments_for(session, event.id)[0].content_hash
    provider = _ScriptedVisionProvider()

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=_vision_pipeline(provider),
    )

    assert result.event_status is LogEventStatus.COMPLETED
    assert result.job_status is EstimationJobStatus.SUCCEEDED

    # The worker loaded the image by event id and fed it to every parse sample.
    assert provider.parse_image_counts and all(n == 1 for n in provider.parse_image_counts)
    assert provider.panel_image_counts == [1]

    # amount = 2 (text-stated) × the label's 40 g serving → 80 g of per-100g
    # 500/25/50/20 → 400 kcal / 20 P / 40 C / 16 F, computed deterministically.
    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event.id)
    ).one()
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.amount == 2
    assert food.grams == 80.0
    assert food.calories == 400.0
    assert food.protein_g == 20.0
    assert food.carbs_g == 40.0
    assert food.fat_g == 16.0

    # Per-surface provenance: the evidence row carries the image surface
    # (``user_label`` + the source image's content hash + per-100g snapshot),
    # while the item keeps the text surface's count; the content-free assumption
    # names the split.
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == food.id)
    ).one()
    assert evidence.source_type == USER_LABEL_SOURCE_TYPE
    assert evidence.source_ref == f"{USER_LABEL_SOURCE_TYPE}:{content_hash}"
    assert evidence.content_hash == content_hash
    assert evidence.calories_per_100g == 500.0
    assert evidence.protein_per_100g == 25.0
    assert evidence.carbs_per_100g == 50.0
    assert evidence.fat_per_100g == 20.0
    assert evidence.assumptions is not None
    assert AMOUNT_FROM_TEXT_ASSUMPTION in evidence.assumptions

    run = _run_for(session, event.id)
    assert run.status == EstimationRunStatus.COMPLETED
    assert "user_label" in run.source_refs

    # Redaction: no image bytes/hash in the sanitized run surfaces or logs.
    trace_dump = json.dumps(run.trace)
    assert content_hash not in trace_dump
    assert content_hash not in (run.error or "")
    assert content_hash not in caplog.text

    # Terminal purge: the transient image did not survive completion.
    assert _attachments_for(session, event.id) == []


class _SweepUnresolvedStep:
    """Stand-in for the food step's bucket invariant: every candidate the rank-1
    tiers did not claim is sorted into the ``unresolved`` persistence bucket."""

    name = "sweep_unresolved"

    def run(self, context: EstimationContext) -> None:
        context.unresolved_food_candidates.extend(context.food_candidates)
        context.food_candidates = []


def test_text_only_and_image_only_components_keep_their_own_provenance(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mixed entry with a second, unpictured component: the label backs only
    the component it names; the other candidate falls through to the ordinary
    tiers (stubbed here as the unresolved bucket) with its own provenance."""

    monkeypatch.setenv("SLACKS_LLM_SUPPORTS_VISION", "true")
    parse_payload = {
        **_PARSE_PAYLOAD,
        "items": [
            *_PARSE_PAYLOAD["items"],
            {
                "type": "food",
                "name": "banana",
                "quantity_text": "1",
                "unit": None,
                "amount": 1,
            },
        ],
    }
    event = _seed_image_event(session, user, "2 of these bars and a banana")
    provider = _ScriptedVisionProvider(parse_payload=parse_payload)

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=Pipeline(
            [ParseStep(provider), ImageFactsResolveStep(provider), _SweepUnresolvedStep()]
        ),
    )

    assert result.event_status is LogEventStatus.COMPLETED
    rows = {
        row.name: row
        for row in session.scalars(
            select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event.id)
        )
    }
    assert rows["protein bar"].status == DerivedItemStatus.RESOLVED
    assert rows["banana"].status == DerivedItemStatus.UNRESOLVED
    evidence = session.scalars(select(EvidenceSource)).all()
    assert {row.derived_food_item_id for row in evidence} == {rows["protein bar"].id}


# ---------------------------------------------------------------------------
# Multi-image events: no residual mis-attribution, no crash
# ---------------------------------------------------------------------------


def test_multi_image_event_does_not_misattribute_residual_candidate(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two images, two candidates, and only one image names a candidate: after
    the protein-bar panel claims the protein bar, the granola panel must NOT be
    attributed to the residual yogurt (the single-candidate shortcut does not
    apply to a residual candidate) — the yogurt falls through to the ordinary
    tiers with no fabricated ``user_label`` provenance."""

    monkeypatch.setenv("SLACKS_LLM_SUPPORTS_VISION", "true")
    parse_payload = {
        **_PARSE_PAYLOAD,
        "items": [
            *_PARSE_PAYLOAD["items"],
            {
                "type": "food",
                "name": "yogurt",
                "quantity_text": "1",
                "unit": None,
                "amount": 1,
            },
        ],
    }
    event = _seed_image_event(
        session,
        user,
        "a protein bar and a yogurt",
        images=[_PNG_IMAGE, _PNG_IMAGE_2],
    )
    provider = _ScriptedVisionProvider(
        parse_payload=parse_payload,
        panel_payloads={_PNG_BYTES: _PANEL_PAYLOAD, _PNG_BYTES_2: _GRANOLA_PANEL_PAYLOAD},
    )

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=Pipeline(
            [ParseStep(provider), ImageFactsResolveStep(provider), _SweepUnresolvedStep()]
        ),
    )

    assert result.event_status is LogEventStatus.COMPLETED
    rows = {
        row.name: row
        for row in session.scalars(
            select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event.id)
        )
    }
    assert rows["protein bar"].status == DerivedItemStatus.RESOLVED
    assert rows["yogurt"].status == DerivedItemStatus.UNRESOLVED

    # Exactly one user_label attribution: the bar image's facts on the bar item.
    # The granola panel named neither candidate, so nothing carries its hash or
    # its per-100g numbers.
    evidence = session.scalars(select(EvidenceSource)).all()
    assert [row.derived_food_item_id for row in evidence] == [rows["protein bar"].id]
    bar_hash = hashlib.sha256(_PNG_BYTES).hexdigest()
    assert evidence[0].content_hash == bar_hash
    assert evidence[0].calories_per_100g == 500.0


def test_multi_image_event_with_fewer_candidates_than_panels_completes(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One candidate, two legible panels: once the candidate is claimed the loop
    stops instead of matching against an empty list — the event completes; it is
    never terminally rejected (estimate-first / never-reject)."""

    monkeypatch.setenv("SLACKS_LLM_SUPPORTS_VISION", "true")
    event = _seed_image_event(session, user, images=2)
    provider = _ScriptedVisionProvider()

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=_vision_pipeline(provider),
    )

    assert result.event_status is LogEventStatus.COMPLETED
    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.should_retry is False
    # The second image was never read: no candidate was left for it to describe.
    assert provider.panel_image_counts == [1]
    food = session.scalars(
        select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event.id)
    ).one()
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.grams == 80.0
    assert _attachments_for(session, event.id) == []  # terminal purge still fires


def test_multi_image_single_candidate_requires_the_panel_to_name_it(session: Session) -> None:
    """A multi-image event (the scoped re-estimate shape: every event image
    re-fed against one component) gets no single-candidate shortcut: a panel
    that does not name the candidate attributes nothing, and the candidate is
    left for the ordinary tiers."""

    provider = _ScriptedVisionProvider(
        panel_payloads={
            _PNG_BYTES: _GRANOLA_PANEL_PAYLOAD,
            _PNG_BYTES_2: _GRANOLA_PANEL_PAYLOAD,
        }
    )
    step = ImageFactsResolveStep(provider)
    context = EstimationContext(
        log_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text="a yogurt",
    )
    context.food_candidates = [
        CandidateDraft(name="yogurt", quantity_text="1", unit=None, amount=1.0)
    ]
    context.images = (
        EventImage(
            image=ImageInput(data=_PNG_BYTES, media_type="image/png"),
            content_hash="a" * 64,
        ),
        EventImage(
            image=ImageInput(data=_PNG_BYTES_2, media_type="image/png"),
            content_hash="b" * 64,
        ),
    )

    step.run(context)

    assert len(context.food_candidates) == 1  # left for USDA/OFF/official tiers
    assert context.resolved_food_items == []
    assert {"step": "image_facts_resolve", "status": "no_usable_label"} in context.trace


# ---------------------------------------------------------------------------
# Text-only regression
# ---------------------------------------------------------------------------


def test_text_only_event_estimates_exactly_as_today(session: Session, user: User) -> None:
    """No images → the prompt and provider calls are byte-identical to today."""

    event = _seed_image_event(session, user, "2 protein bars", images=0)
    provider = _ScriptedVisionProvider(supports_vision=False)

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=_vision_pipeline(provider),
    )

    assert result.event_status is LogEventStatus.COMPLETED
    assert provider.parse_image_counts and all(n == 0 for n in provider.parse_image_counts)
    assert provider.panel_image_counts == []
    assert provider.parse_prompts[0] == build_parse_prompt("2 protein bars")
    run = _run_for(session, event.id)
    assert IMAGE_EVIDENCE_UNAVAILABLE_ASSUMPTION not in run.assumptions


# ---------------------------------------------------------------------------
# Estimate-first degradation
# ---------------------------------------------------------------------------


def test_transient_provider_error_retries_then_estimates_never_terminal(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient error keeps the event honestly ``processing`` (still working)
    and a later attempt estimates — the entry is never terminally rejected."""

    monkeypatch.setenv("SLACKS_LLM_SUPPORTS_VISION", "true")
    event = _seed_image_event(session, user)

    failing = _ScriptedVisionProvider(parse_error=LLMTransientError("boom"))
    first = process_estimation(
        session, log_event_id=event.id, user_id=user.id, pipeline=_vision_pipeline(failing)
    )
    assert first.should_retry is True
    assert first.event_status is LogEventStatus.PROCESSING
    assert first.job_status is EstimationJobStatus.RUNNING
    # The awaiting-retry window retains the images for the next attempt.
    assert len(_attachments_for(session, event.id)) == 1

    second = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=_vision_pipeline(_ScriptedVisionProvider()),
    )
    assert second.event_status is LogEventStatus.COMPLETED
    assert second.should_retry is False


def test_label_read_provider_error_degrades_to_downstream_tiers(session: Session) -> None:
    """A provider failure on the image read is never fatal: the candidate stays
    for the ordinary tiers and the step records a content-free degrade."""

    provider = _ScriptedVisionProvider(panel_error=LLMTransientError("boom"))
    step = ImageFactsResolveStep(provider)
    context = EstimationContext(
        log_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text="2 of these bars",
    )
    context.food_candidates = [
        CandidateDraft(name="protein bar", quantity_text="2", unit="bars", amount=2.0)
    ]
    context.images = (
        EventImage(
            image=ImageInput(data=_PNG_BYTES, media_type="image/png"),
            content_hash="a" * 64,
        ),
    )

    step.run(context)

    assert len(context.food_candidates) == 1  # left for USDA/OFF/official tiers
    assert context.resolved_food_items == []
    assert {"step": "image_facts_resolve", "status": "degraded_provider_error"} in context.trace


def test_vision_unavailable_degrades_to_text_only_estimation(session: Session, user: User) -> None:
    """Images + a non-vision model: text-only estimation with an honest
    content-free assumption — never a leaked image, never a failure."""

    event = _seed_image_event(session, user)
    provider = _ScriptedVisionProvider(supports_vision=False)

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=_vision_pipeline(provider),
    )

    assert result.event_status is LogEventStatus.COMPLETED
    assert provider.parse_image_counts and all(n == 0 for n in provider.parse_image_counts)
    assert provider.panel_image_counts == []
    assert provider.parse_prompts[0] == build_parse_prompt("2 of these bars")
    run = _run_for(session, event.id)
    assert IMAGE_EVIDENCE_UNAVAILABLE_ASSUMPTION in run.assumptions


def test_image_only_event_without_vision_clarifies_never_fails(
    session: Session, user: User
) -> None:
    """The photo-marker event on a non-vision deployment routes to a clarifying
    question with no provider call — never ``unparseable``/terminal ``failed``."""

    assert PHOTO_ONLY_MARKER_TEXT == PHOTO_LOG_EVENT_RAW_TEXT
    event = _seed_image_event(session, user, PHOTO_ONLY_MARKER_TEXT)
    provider = _ScriptedVisionProvider(supports_vision=False)

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=_vision_pipeline(provider),
    )

    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert provider.parse_prompts == []
    question = session.scalars(
        select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event.id)
    ).one()
    assert question.question_text == PHOTO_WITHOUT_VISION_QUESTION
    # Worker-terminal, not event-terminal: the images await the answer.
    assert len(_attachments_for(session, event.id)) == 1


# ---------------------------------------------------------------------------
# Terminal purge on every event-terminal path; retention across clarify
# ---------------------------------------------------------------------------


class _FailStep:
    """A scripted failing step: transient by default, deterministic on demand."""

    name = "fails"

    def __init__(self, error: Exception) -> None:
        self._error = error

    def run(self, context: EstimationContext) -> None:
        raise self._error


def test_completed_purges_transient_and_keeps_saved_images(session: Session, user: User) -> None:
    event = _seed_image_event(session, user)
    stage_submission_images(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=event.id,
        images=[_PNG_IMAGE],
        save=True,
    )
    session.commit()

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=Pipeline([StubParseStep(), StubCalculateStep()]),
    )

    assert result.event_status is LogEventStatus.COMPLETED
    remaining = _attachments_for(session, event.id)
    assert [row.transient for row in remaining] == [False]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(StepFailed("unparseable_input"), id="deterministic-step-failure"),
        pytest.param(StepFailed(WALL_CLOCK_DEADLINE_EXCEEDED), id="run-budget-ceiling"),
    ],
)
def test_terminal_failed_paths_purge_transient_images(
    session: Session, user: User, error: Exception
) -> None:
    event = _seed_image_event(session, user)

    result = process_estimation(
        session,
        log_event_id=event.id,
        user_id=user.id,
        pipeline=Pipeline([_FailStep(error)]),
    )

    assert result.event_status is LogEventStatus.FAILED
    assert result.should_retry is False
    assert _attachments_for(session, event.id) == []


def test_retry_exhaustion_purges_transient_images_at_terminal(session: Session, user: User) -> None:
    event = _seed_image_event(session, user)
    pipeline = Pipeline([_FailStep(StepError("transient"))])

    first = process_estimation(
        session, log_event_id=event.id, user_id=user.id, pipeline=pipeline, max_attempts=2
    )
    assert first.should_retry is True
    assert len(_attachments_for(session, event.id)) == 1  # retained mid-retry

    second = process_estimation(
        session, log_event_id=event.id, user_id=user.id, pipeline=pipeline, max_attempts=2
    )
    assert second.event_status is LogEventStatus.FAILED
    assert _attachments_for(session, event.id) == []


def test_needs_clarification_retains_transient_images_for_the_answer(
    session: Session, user: User
) -> None:
    """Worker-terminal clarification purges nothing: the answer-triggered
    re-estimate must be able to reload the images (``log-attachments.md`` v3)."""

    event = _seed_image_event(session, user)

    class _ClarifyStep:
        name = "asks"

        def run(self, context: EstimationContext) -> None:
            context.clarification_questions = [ClarificationDraft(text="Which bar was it?")]
            raise NeedsClarification("ambiguous")

    result = process_estimation(
        session, log_event_id=event.id, user_id=user.id, pipeline=Pipeline([_ClarifyStep()])
    )

    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    rows = _attachments_for(session, event.id)
    assert [row.transient for row in rows] == [True]


# ---------------------------------------------------------------------------
# Worker image load unit behaviour
# ---------------------------------------------------------------------------


def test_load_event_images_is_scoped_to_the_owner(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLACKS_LLM_SUPPORTS_VISION", "true")
    event = _seed_image_event(session, user)

    own = load_event_images(session, event.id, user.id)
    assert len(own.images) == 1
    assert own.degraded_reason is None

    cross = load_event_images(session, event.id, uuid.uuid4())
    assert cross.images == ()
    assert cross.degraded_reason is None

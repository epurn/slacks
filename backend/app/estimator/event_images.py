"""Worker-side image evidence loading for mixed text+image events (FTY-376).

The unified text+image submission (``docs/contracts/log-event-images.md``)
persists each validated image as a ``log_attachments`` row tied to the created
event (FTY-375), so the ids-only estimation job payload never carries image
bytes, paths, or hashes. At claim time the worker loads the event's images
**by event id, scoped to the job's owner**, and attaches them to the
:class:`~app.estimator.pipeline.EstimationContext` as vision evidence surfaces
(``estimation-jobs.md`` v6).

Vision gating lives here too: images are supplied to the pipeline only when the
configured model is vision-capable (``SLACKS_LLM_SUPPORTS_VISION``). On a
non-vision deployment the load **degrades instead of failing** — the run
proceeds on the text surface alone as a visibly rough estimate (the
estimate-first / never-reject clause: a configuration limit is infrastructure
trouble, never grounds for a terminal ``failed``), and an image-only event
routes to a clarifying question (see :mod:`app.estimator.parse`).

Privacy: the loaded bytes go to the LLM/vision provider only. Nothing here is
logged, and the bytes/hashes never enter the run ``trace``/``error`` — the
evidence row's ``content_hash`` provenance is written by the resolution step to
``evidence_sources`` (``docs/contracts/interpretation-session.md`` v2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm import ImageInput, load_llm_settings
from app.models.attachments import LogAttachment

#: The content-free ``raw_text`` marker stored for an image-only submission
#: (``log-event-images.md``). Owned by the multipart create route
#: (``app.routers.log_event_multipart.PHOTO_LOG_EVENT_RAW_TEXT``); mirrored here
#: so the estimator can recognise "no usable text surface" without importing
#: router code — a sync test asserts the two constants stay equal.
PHOTO_ONLY_MARKER_TEXT = "Photo log"

#: Content-free degrade reason when an image-bearing event runs on a deployment
#: whose configured model is not vision-capable. Recorded on the context, never
#: raised — the run continues on the text surface (estimate-first).
VISION_NOT_CONFIGURED = "vision_not_configured"

#: Content-free assumption persisted on the run when the event's images could
#: not be read (non-vision deployment), so the text-only estimate is honestly
#: labelled as missing its image evidence.
IMAGE_EVIDENCE_UNAVAILABLE_ASSUMPTION = "image_evidence_unavailable: vision_not_configured"

#: Fixed clarifying question for an image-only event on a non-vision deployment:
#: there is no usable text surface to estimate from, so the honest route is a
#: question, never a terminal failure (``estimation-jobs.md`` v6).
PHOTO_WITHOUT_VISION_QUESTION = (
    "We couldn't read your photo on this server. What did you have, and how much?"
)


@dataclass(frozen=True)
class EventImage:
    """One validated event image plus its stable evidence reference.

    ``image`` carries the raw bytes to the vision provider (the only egress an
    image is ever allowed — ``llm-provider.md`` v2); ``content_hash`` is the
    SHA-256 the FTY-375 ingest computed, reused verbatim as the ``user_label``
    evidence reference so a saved image and its extracted facts correlate.
    """

    image: ImageInput
    content_hash: str


@dataclass(frozen=True)
class EventImageLoad:
    """The worker's per-claim image load result.

    ``images`` is empty for a plain text event. ``degraded_reason`` is set when
    the event *has* images that cannot be attached (non-vision deployment) so
    the parse step can degrade honestly instead of silently dropping evidence.
    """

    images: tuple[EventImage, ...] = ()
    degraded_reason: str | None = None


def load_event_images(
    session: Session, log_event_id: uuid.UUID, user_id: uuid.UUID
) -> EventImageLoad:
    """Load the event's image attachments by id, gated on vision capability.

    Rows are loaded scoped to the owning ``user_id`` like the event itself
    (``estimation-jobs.md`` v6 — a cross-user row is unreachable by
    construction), in creation order. Both retention classes are included: a
    transient mixed-submission image and a saved one are the same evidence
    surface; retention only governs what survives the terminal purge.

    When the configured model is not vision-capable the images are **not**
    attached (an image must never reach a non-vision path) and the load reports
    :data:`VISION_NOT_CONFIGURED` so the run degrades per estimate-first.
    """

    rows = session.scalars(
        select(LogAttachment)
        .where(
            LogAttachment.log_event_id == log_event_id,
            LogAttachment.user_id == user_id,
        )
        .order_by(LogAttachment.created_at.asc(), LogAttachment.id.asc())
    ).all()
    if not rows:
        return EventImageLoad()
    if not load_llm_settings().supports_vision:
        return EventImageLoad(degraded_reason=VISION_NOT_CONFIGURED)
    return EventImageLoad(
        images=tuple(
            EventImage(
                image=ImageInput(data=row.data, media_type=row.content_type),
                content_hash=row.content_hash,
            )
            for row in rows
        )
    )

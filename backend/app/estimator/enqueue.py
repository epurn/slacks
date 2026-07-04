"""Estimation enqueue seam (FTY-040).

The log-event create path publishes an estimation job through an
:class:`EstimationEnqueuer` rather than calling Celery directly. This keeps the
broker a swappable seam: production wires :func:`celery_enqueuer` (publish to
Redis), while tests inject a recording fake so creating an event never needs a
live broker. The active enqueuer lives on ``app.state`` and is resolved per
request by :func:`get_enqueuer`.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from fastapi import Request


class EstimationEnqueuer(Protocol):
    """Publishes an estimation job for a freshly created log event."""

    def __call__(self, *, log_event_id: uuid.UUID, user_id: uuid.UUID) -> None: ...


def celery_enqueuer(*, log_event_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Publish the estimation task to the Celery/Redis broker.

    The task module is imported lazily so importing this module (and the FastAPI
    app) does not require the Celery app or broker to be importable in contexts
    that never enqueue.
    """

    from app.estimator.tasks import process_log_event_task  # noqa: PLC0415 — lazy (see docstring)

    process_log_event_task.delay(str(log_event_id), str(user_id))


def get_enqueuer(request: Request) -> EstimationEnqueuer:
    """FastAPI dependency returning the app's active estimation enqueuer."""

    enqueuer: EstimationEnqueuer = request.app.state.estimation_enqueuer
    return enqueuer

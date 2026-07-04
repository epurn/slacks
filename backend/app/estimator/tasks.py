"""Celery task wiring for the estimation worker (FTY-040).

This module registers the single estimation task on the Celery app
(:data:`app.worker.celery_app`). The task is a thin shell: it validates the
payload at the trust boundary, opens a database session, delegates to the
idempotent, retry-aware :func:`app.estimator.processing.process_estimation`
core, and schedules a bounded exponential-backoff retry when that core reports a
transient failure. All estimation logic and the state machine live in the core
so they can be tested without a broker.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session, sessionmaker

from app.db import create_db_engine, create_session_factory
from app.estimator.processing import (
    DEFAULT_MAX_ATTEMPTS,
    process_estimation,
    retry_countdown,
)
from app.schemas.estimation import EstimationJobPayload
from app.settings import load_settings
from app.worker import celery_app

logger = logging.getLogger(__name__)

#: Celery retry bound mirrors the processing core's attempt bound: the first try
#: plus ``DEFAULT_MAX_ATTEMPTS - 1`` retries.
MAX_RETRIES = DEFAULT_MAX_ATTEMPTS - 1

_session_factory: sessionmaker[Session] | None = None


def _get_session_factory() -> sessionmaker[Session]:
    """Build (once) the worker's session factory from settings.

    The worker process owns its own engine/session factory, distinct from the
    request-scoped factory the FastAPI app builds, so it works whether or not the
    web app is running in the same process.
    """

    global _session_factory  # noqa: PLW0603 — module-level lazy singleton for the worker process
    if _session_factory is None:
        settings = load_settings()
        _session_factory = create_session_factory(create_db_engine(settings.database_url))
    return _session_factory


@celery_app.task(  # type: ignore[untyped-decorator]  # celery is untyped under strict mypy
    bind=True,
    name="estimation.process_log_event",
    max_retries=MAX_RETRIES,
)
def process_log_event_task(self: object, log_event_id: str, user_id: str) -> str:
    """Process one log event's estimation; retry on transient failure.

    ``log_event_id`` / ``user_id`` are the serialized :class:`EstimationJobPayload`.
    Returns the resolved job status string (for result-backend visibility). Only
    ids are logged — never raw text.
    """

    # model_validate coerces the string ids and rejects a malformed/padded
    # message at the worker trust boundary.
    payload = EstimationJobPayload.model_validate(
        {"log_event_id": log_event_id, "user_id": user_id}
    )
    factory = _get_session_factory()
    with factory() as session:
        result = process_estimation(
            session,
            log_event_id=payload.log_event_id,
            user_id=payload.user_id,
        )

    if result.should_retry:
        countdown = retry_countdown(self.request.retries)  # type: ignore[attr-defined]
        logger.info(
            "estimation attempt failed; retrying",
            extra={
                "log_event_id": str(payload.log_event_id),
                "attempts": result.attempts,
                "countdown_seconds": countdown,
            },
        )
        raise self.retry(countdown=countdown)  # type: ignore[attr-defined]

    return str(result.job_status)

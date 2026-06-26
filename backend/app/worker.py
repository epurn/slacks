"""Celery application for background jobs.

FTY-011 wires a Celery worker into the local Docker Compose stack. This module
defines the Celery application and points its broker and result backend at Redis
(``FATTY_REDIS_URL``); it deliberately registers **no task definitions** — real
estimator tasks are deferred to later stories. ``celery -A app.worker:celery_app
worker`` is the entrypoint the compose worker service runs.
"""

from __future__ import annotations

from celery import Celery

from app.settings import Settings, load_settings


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Build the Celery application from validated settings.

    The Redis URL is used as both the broker and the result backend for local
    development. Settings may be injected by tests; otherwise they are loaded
    from the environment.
    """

    settings = settings or load_settings()
    application: Celery = Celery(
        "fatty",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    return application


celery_app = create_celery_app()

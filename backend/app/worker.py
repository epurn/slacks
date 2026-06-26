"""Celery application for background jobs.

FTY-011 wires a Celery worker into the local Docker Compose stack; FTY-040 adds
the first task. This module defines the Celery application, points its broker and
result backend at Redis (``FATTY_REDIS_URL``), and lists the task modules Celery
imports on worker start. ``celery -A app.worker:celery_app worker`` is the
entrypoint the compose worker service runs.

The estimation task itself lives in :mod:`app.estimator.tasks` and is discovered
via the ``include`` list below; keeping it out of this module avoids an import
cycle (the task module imports :data:`celery_app` from here).
"""

from __future__ import annotations

from celery import Celery

from app.settings import Settings, load_settings

#: Task modules Celery imports (and thus registers the tasks from) at startup.
TASK_MODULES = ["app.estimator.tasks"]


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Build the Celery application from validated settings.

    The Redis URL is used as both the broker and the result backend for local
    development. Settings may be injected by tests; otherwise they are loaded
    from the environment. Task modules in :data:`TASK_MODULES` are imported on
    worker start so their tasks register.
    """

    settings = settings or load_settings()
    application: Celery = Celery(
        "fatty",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=TASK_MODULES,
    )
    return application


celery_app = create_celery_app()

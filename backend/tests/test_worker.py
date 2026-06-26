"""Celery worker wiring tests."""

from __future__ import annotations

from app.settings import Settings
from app.worker import create_celery_app


def test_celery_app_uses_redis_url_for_broker_and_backend() -> None:
    settings = Settings(redis_url="redis://redis:6379/2")

    celery_app = create_celery_app(settings)

    assert celery_app.conf.broker_url == "redis://redis:6379/2"
    assert celery_app.conf.result_backend == "redis://redis:6379/2"


def test_celery_app_registers_no_user_tasks() -> None:
    # FTY-011 wires the worker only; task definitions are an explicit non-goal,
    # so nothing beyond Celery's built-in tasks should be registered.
    celery_app = create_celery_app(Settings())

    user_tasks = [name for name in celery_app.tasks if not name.startswith("celery.")]

    assert user_tasks == []

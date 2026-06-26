"""Celery worker wiring tests."""

from __future__ import annotations

from app.settings import Settings
from app.worker import create_celery_app


def test_celery_app_uses_redis_url_for_broker_and_backend() -> None:
    settings = Settings(redis_url="redis://redis:6379/2")

    celery_app = create_celery_app(settings)

    assert celery_app.conf.broker_url == "redis://redis:6379/2"
    assert celery_app.conf.result_backend == "redis://redis:6379/2"


def test_celery_app_includes_estimation_task_module() -> None:
    # FTY-040 adds the first task. The app lists its task modules in ``include``
    # so Celery imports and registers them on worker start.
    celery_app = create_celery_app(Settings())

    assert "app.estimator.tasks" in celery_app.conf.include


def test_estimation_task_is_registered() -> None:
    # Importing the task module registers the single estimation task on the
    # module-level app (the worker entrypoint ``app.worker:celery_app``).
    import app.estimator.tasks  # noqa: F401  (import registers the task)
    from app.worker import celery_app

    user_tasks = [name for name in celery_app.tasks if not name.startswith("celery.")]

    assert user_tasks == ["estimation.process_log_event"]

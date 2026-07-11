"""Optional live-provider smoke for the FTY-302 representative corpus.

Skipped by default. When explicitly enabled by an operator, only synthetic fixture
phrases marked for smoke are sent to the configured parse provider. Nutrition,
search, and fetch seams stay network-free, and the optional summary records only
case ids plus status/pass-fail values.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.estimator.processing import process_estimation
from app.llm import LLMSettings, build_provider, load_llm_settings
from tests.estimate_first_representative_harness import (
    build_pipeline,
    case_id,
    expectation,
    seed_event,
    set_weight,
    smoke_cases,
    static_model_provider,
)

_ENABLE_ENV = "SLACKS_ESTIMATE_FIRST_LIVE_SMOKE"
_SUMMARY_ENV = "SLACKS_ESTIMATE_FIRST_LIVE_SMOKE_SUMMARY"


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def test_optional_live_provider_smoke_statuses_are_content_free(
    client: TestClient, session: Session
) -> None:
    settings = _live_settings_or_skip()
    provider = build_provider(settings)
    rows: list[dict[str, str | bool]] = []

    for case in smoke_cases():
        user_id, event_id = seed_event(client, case, "estimate_first")
        set_weight(session, user_id)
        pipeline = build_pipeline(
            session,
            mode="estimate_first",
            parse_provider=provider,
            model_provider=static_model_provider(),
        )

        result = process_estimation(
            session, log_event_id=event_id, user_id=user_id, pipeline=pipeline
        )
        expected_status = str(expectation(case, "estimate_first")["event_status"])
        actual_status = str(result.event_status)
        rows.append(
            {
                "case_id": case_id(case),
                "expected_status": expected_status,
                "actual_status": actual_status,
                "passed": actual_status == expected_status,
            }
        )

    _write_summary(rows)
    assert rows
    assert all(bool(row["passed"]) for row in rows)


def _live_settings_or_skip() -> LLMSettings:
    if os.environ.get(_ENABLE_ENV) != "1":
        pytest.skip(f"{_ENABLE_ENV}=1 not set; skipping optional live-provider smoke")
    try:
        settings = load_llm_settings()
    except ValidationError as exc:
        pytest.skip(f"live provider settings are incomplete: {type(exc).__name__}")
    if settings.provider == "fake":
        pytest.skip("SLACKS_LLM_PROVIDER=fake is not a live provider")
    return settings


def _write_summary(rows: list[dict[str, str | bool]]) -> None:
    target = os.environ.get(_SUMMARY_ENV)
    if not target:
        return
    Path(target).write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")

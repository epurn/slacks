"""OpenAPI contract snapshot test (FTY-141).

This test guards drift between the server's generated OpenAPI surface and the
documented contracts in ``docs/contracts/``. Any change to the API (renamed field,
changed status, dropped/added route, loosened type, etc.) produces a snapshot diff
that must be reviewed alongside the contract documentation.

To regenerate the snapshot after an intentional change, run:

    UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi_snapshot.py

The test will rewrite the fixture and exit. On an unchanged app, regeneration is
idempotent (produces no fixture diff).

See ``docs/contracts/README.md`` for the contract governance model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.main import create_app
from app.settings import Settings


def load_snapshot() -> dict[str, Any]:
    """Load the canonical OpenAPI snapshot fixture."""
    snapshot_path = Path(__file__).parent / "snapshots" / "openapi.json"
    with open(snapshot_path) as f:
        return json.load(f)  # type: ignore[no-any-return]


def save_snapshot(schema: dict[str, Any]) -> None:
    """Write the OpenAPI schema to the snapshot fixture with deterministic formatting."""
    snapshot_path = Path(__file__).parent / "snapshots" / "openapi.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w") as f:
        json.dump(schema, f, indent=2, sort_keys=True)


def test_openapi_schema_snapshot() -> None:
    """Assert the app's current OpenAPI schema matches the checked-in snapshot.

    Fails with a clear message pointing to the regeneration command when they
    diverge, so an intentional change shows up as a reviewable diff.
    """
    # Build the app with test settings to ensure OpenAPI is enabled
    app = create_app(Settings(environment="test", log_level="WARNING"))
    current_schema = app.openapi()

    # If UPDATE_OPENAPI_SNAPSHOT env var is set, rewrite the fixture instead
    if os.getenv("UPDATE_OPENAPI_SNAPSHOT"):
        save_snapshot(current_schema)
        return

    # Load the canonical snapshot and assert deep equality
    fixture = load_snapshot()
    assert current_schema == fixture, (
        "OpenAPI schema diverged from snapshot (FTY-141). "
        "Review the diff and update the contract if intentional:\n"
        "    UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi_snapshot.py"
    )

"""Typed application settings.

Settings are validated Pydantic models loaded from environment variables at
startup. Invalid or out-of-range values fail fast with a clear ``ValidationError``
rather than silently degrading. The environment-variable names below are a
contract consumed by infra (Docker Compose) and later backend stories.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Environment variables are read with this prefix, e.g. ``FATTY_LOG_LEVEL``.
ENV_PREFIX = "FATTY_"

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseModel):
    """Validated application configuration.

    Frozen and ``extra="forbid"`` so configuration is immutable once loaded and
    unknown keys are rejected instead of being silently ignored.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_name: str = Field(default="fatty-backend", min_length=1)
    environment: Environment = "development"
    log_level: LogLevel = "INFO"
    # Bind to loopback by default; deployments (e.g. Docker Compose) override
    # FATTY_HOST to expose the service. Avoids binding all interfaces silently.
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    # Service URLs. Defaults target a developer's localhost; Docker Compose
    # overrides them to the compose service hostnames (see repo-root
    # ``.env.example``). These FATTY_-prefixed names are part of the FTY-011
    # local-infra env-var contract. ``database_url`` is reserved for the later
    # database story and is not consumed yet; ``redis_url`` is the Celery
    # worker's broker and result backend.
    database_url: str = Field(default="postgresql://fatty:fatty@localhost:5432/fatty", min_length=1)
    redis_url: str = Field(default="redis://localhost:6379/0", min_length=1)


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from environment variables.

    Only ``FATTY_``-prefixed variables matching a known field are read; missing
    values fall back to defaults and invalid values raise ``ValidationError``.
    """

    source = os.environ if environ is None else environ
    data: dict[str, str] = {}
    for field in Settings.model_fields:
        key = ENV_PREFIX + field.upper()
        if key in source:
            data[field] = source[key]
    # model_validate so Pydantic coerces the raw string values (e.g. port) and
    # reports invalid required settings as a clear ValidationError.
    return Settings.model_validate(data)

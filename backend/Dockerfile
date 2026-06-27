# syntax=docker/dockerfile:1
#
# Backend image for the local Docker Compose dev stack (FTY-011). Builds the
# FastAPI app and the Celery worker from the same package; compose selects which
# process to run via the service command. Plain HTTP, local dev only — TLS and
# production hardening are out of scope.

# Pinned base image per the security baseline's pinned-dependency principle.
FROM python:3.12-slim-bookworm

# uv (pinned) manages the locked Python environment for reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    # Bind all interfaces inside the container so the host can reach the API.
    FATTY_HOST=0.0.0.0 \
    FATTY_PORT=8000

# Install locked production dependencies first for a cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application source.
COPY app ./app

# Alembic migrations — needed by the migrate init service (FTY-072).
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

# Default to the API; the worker service overrides this command in compose.
CMD [".venv/bin/python", "-m", "app"]

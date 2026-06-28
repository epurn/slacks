# syntax=docker/dockerfile:1
#
# Backend image for the local Docker Compose dev stack (FTY-011). Builds the
# FastAPI app and the Celery worker from the same package; compose selects which
# process to run via the service command. Plain HTTP, local dev only — TLS and
# production hardening are out of scope.

# Pinned base image per the security baseline's pinned-dependency principle.
FROM python:3.14-slim-bookworm

# uv (pinned) manages the locked Python environment for reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /usr/local/bin/

# ---------------------------------------------------------------------------
# Claude Code CLI (FTY-088): Install Node.js LTS + the Claude Code CLI so the
# Celery worker and API can invoke 'claude' in headless mode for the claude_code
# LLM provider (FTY-087). Both versions are pinned per the security baseline's
# pinned-dependency principle. NO credentials are added here — only the binary
# and its runtime. The operator's Claude Code session is mounted at runtime via
# the compose claude-config volume; nothing session-related is baked in.
# ---------------------------------------------------------------------------
ARG NODE_MAJOR=22
ARG CLAUDE_CODE_VERSION=1.0.18

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && printf 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_%s.x nodistro main\n' "${NODE_MAJOR}" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

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

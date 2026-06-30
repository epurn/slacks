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
#
# CLAUDE_CODE_VERSION pin rationale (FTY-150): the pin MUST track a CLI release
# new enough to recognise the model id set in FATTY_LLM_MODEL. Older releases
# (e.g. 1.0.18) default to a retired model id and return 404 on every provider
# call, making the claude_code subscription path dead on arrival. Verified
# working on 2.1.195 during v1 RC dogfooding; pinned to the latest stable at
# implementation time. The CLI evolves quickly — a stale pin silently breaks the
# provider, so bump this when upgrading the configured model or when a newer
# release fixes a relevant bug.
# ---------------------------------------------------------------------------
ARG NODE_MAJOR=22
ARG CLAUDE_CODE_VERSION=2.1.196

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

# Non-root runtime user (FTY-116): fixed UID/GID keeps ownership stable across
# rebuilds; a real home dir gives the claude CLI a writable scratch location.
RUN groupadd --gid 10001 fatty \
    && useradd --uid 10001 --gid fatty --shell /bin/bash --create-home fatty

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    # Bind all interfaces inside the container so the host can reach the API.
    FATTY_HOST=0.0.0.0 \
    FATTY_PORT=8000 \
    HOME=/home/fatty

# Install locked production dependencies first for a cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application source.
COPY app ./app

# Alembic migrations — needed by the migrate init service (FTY-072).
COPY alembic ./alembic
COPY alembic.ini ./

# Transfer ownership of the app tree (incl. .venv) to the runtime user so all
# three service commands (.venv/bin/python, .venv/bin/alembic, .venv/bin/celery)
# are readable/executable by it. Create the claude-config mountpoint owned by
# the same user so named-volume population inherits the correct owner on first
# use (FTY-116, FTY-088).
RUN chown -R fatty:fatty /app \
    && mkdir -p /claude-config \
    && chown fatty:fatty /claude-config

EXPOSE 8000

USER fatty

# Default to the API; the worker service overrides this command in compose.
CMD [".venv/bin/python", "-m", "app"]

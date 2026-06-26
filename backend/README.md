# backend

The Fatty backend package (FastAPI, Python).

## Owns

- The FastAPI application, settings, and request/response boundary models.
- Service-layer domain behavior (deterministic calorie, macro, and target math).
- Database access, migrations, and background job entrypoints (added in later stories).
- Provider adapters for evidence retrieval and LLM estimation (added in later stories).

## Toolchain

- **uv** manages the Python environment and locks dependencies in `uv.lock`.
  This lockfile convention is shared by all later backend stories.
- **ruff** lints and formats; **mypy** (strict) typechecks; **pytest** runs tests.

```sh
uv sync --dev        # create the environment from uv.lock
uv run python -m app # run the app (uvicorn) on FATTY_HOST:FATTY_PORT
uv run pytest        # run the tests
```

## Layout

- `app/main.py` — `create_app()` application factory (validates settings,
  configures logging, wires routers).
- `app/settings.py` — typed Pydantic settings loaded from environment variables.
- `app/worker.py` — Celery application (`celery_app`) for background jobs; its
  broker and result backend are Redis. No task definitions yet.
- `app/logging.py` — structured JSON logging with sensitive-field redaction.
- `app/llm/` — config-driven LLM provider layer (OpenAI, Anthropic,
  OpenAI-compatible, and an in-memory fake). Exposes a single
  `structured_completion(prompt, schema) -> validated object` capability; see
  [`docs/contracts/llm-provider.md`](../docs/contracts/llm-provider.md).
- `app/routers/` — thin HTTP boundary; handlers delegate to `app/services/`.
- `app/services/` — domain behavior.
- `app/schemas/` — Pydantic request/response models.
- `tests/` — pytest harness.
- `Dockerfile` — builds the API and worker image for the Docker Compose dev
  stack (FTY-011); see the repo-root `docker-compose.yml`.

## Contracts

- `GET /healthz` returns `200 {"status": "ok"}` (consumed by the FTY-011 Docker
  Compose healthcheck and later infra).
- Settings are read from `FATTY_`-prefixed environment variables:

  | Variable | Default | Notes |
  | --- | --- | --- |
  | `FATTY_APP_NAME` | `fatty-backend` | Application title. |
  | `FATTY_ENVIRONMENT` | `development` | One of `development`, `test`, `production`. |
  | `FATTY_LOG_LEVEL` | `INFO` | Standard Python log level. |
  | `FATTY_HOST` | `127.0.0.1` | Bind address; deployments override to expose. |
  | `FATTY_PORT` | `8000` | Bind port (1–65535). |
  | `FATTY_REDIS_URL` | `redis://localhost:6379/0` | Celery broker + result backend. |
  | `FATTY_DATABASE_URL` | `postgresql://fatty:fatty@localhost:5432/fatty` | Postgres DSN; reserved for the later database story (not consumed yet). |

  Invalid or out-of-range values fail fast at startup with a `ValidationError`.
  Under Docker Compose these point at the `redis` and `postgres` service
  hostnames; see the repo-root `docker-compose.yml` and `.env.example`.

- The LLM provider layer is configured from `FATTY_LLM_`-prefixed variables and
  documented as a separate contract; see
  [`docs/contracts/llm-provider.md`](../docs/contracts/llm-provider.md). Keys
  live in the environment only and are never logged or exposed to clients.

## Logging and privacy

Logs are single-line JSON. A redaction filter scrubs any field whose name looks
sensitive (tokens, secrets, keys, passwords, authorization, cookies). Never
attach raw prompts, provider keys, or personal nutrition data to log records;
prefer request/event IDs over personal values.

## Root verification

`backend/verify.sh` is the package hook run by root `make verify` (via
`scripts/package-verify.sh`). It runs `uv sync --frozen`, ruff lint + format
check, mypy, and pytest, and exits non-zero on the first failure. See
[`docs/architecture/repo-layout.md`](../docs/architecture/repo-layout.md).

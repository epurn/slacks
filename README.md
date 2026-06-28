# Fatty

Fatty is an iOS-first, open source calorie and macro tracker for people who hate traditional tracking. Users describe what they ate or did in natural language, and Fatty turns that into structured, editable food and exercise entries with evidence and assumptions.

The product principle is simple: natural input, deterministic math, visible evidence, easy correction.

## Current Status

**v1.0.0** — the first stable release. All v1 milestones are shipped: accounts and profile, the logging spine, the evidence-backed estimator, editing and saved foods, barcode and label evidence inputs, and weight tracking with a daily summary. See [CHANGELOG.md](CHANGELOG.md) for the full feature summary.

## Product Shape

- iOS-first Expo app
- FastAPI backend
- Postgres, Redis, Celery
- Docker Compose self-hosting
- async estimation jobs
- calories and macros only
- MET-based exercise estimates in v1
- nutrition label photo, barcode, text quick-add, manual edits
- source/evidence icons instead of visible confidence ranges
- privacy and data minimization as core requirements

See `docs/architecture/system-overview.md` for the working architecture.

## Self-Hosting

Fatty is designed for self-hosting. The Docker Compose stack brings up Postgres,
Redis, the FastAPI API, and a Celery worker over plain HTTP from a clean checkout.

**Scope:** HTTP-only local self-host. TLS/HTTPS termination, reverse proxy,
production hardening, resource limits, backups, and cloud/Kubernetes deployment
are intentionally out of scope.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- A USDA FoodData Central API key (free, from [fdc.nal.usda.gov/api-guide](https://fdc.nal.usda.gov/api-guide)) if you want generic-food USDA nutrition lookups — optional; the app runs without it
- An LLM API key (OpenAI, Anthropic, or OpenAI-compatible) for full estimation quality — optional; the app starts and serves health with the built-in `fake` provider

### Step-by-Step Bring-Up

**1. Clone and enter the repo:**

```sh
git clone https://github.com/epurn/fatty.git
cd fatty
```

**2. Copy the environment template:**

```sh
cp .env.example .env
```

**3. Generate and set the auth secret** (required before first boot):

```sh
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Open `.env` and replace the `FATTY_AUTH_SECRET` placeholder with the output.
The app will not start in production mode with the placeholder in place.

**4. (Optional) Configure the API host port:**

Only the API publishes a host port by default. If `8000` is already in use on your
host, set it in `.env`:

```sh
API_PORT=8001          # default 8000
```

Postgres and Redis are **not** published to the host by default (FTY-109) — the
`api`, `worker`, and `migrate` services reach them over the internal compose
network. `POSTGRES_PORT` / `REDIS_PORT` are therefore inert unless you add a
loopback-only host mapping for direct datastore access (e.g. a DB GUI or local
`psql`); see [Local Development Stack](docs/operations/local-dev-stack.md) for
that re-enable path.

**5. (Optional) Configure providers:**

Open `.env` and configure any providers you want:
- **LLM:** set `FATTY_LLM_PROVIDER`. Leave `FATTY_LLM_PROVIDER=fake` to skip (estimation degrades gracefully).
  - **Claude subscription (no API key):** if you have a Claude monthly plan, the `claude_code` provider runs estimation through your own subscription — no per-token billing:
    ```
    FATTY_LLM_PROVIDER=claude_code
    # FATTY_LLM_MODEL is optional — Claude Code uses your plan's model by default
    # No FATTY_LLM_API_KEY — auth is your 'claude login' session (see step 5a below)
    ```
    See **Claude Code session setup** (step 5a) to complete the one-time login.
  - **Zero-cost local model:** run [Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai), or [vLLM](https://github.com/vllm-project/vllm) locally, then set:
    ```
    FATTY_LLM_PROVIDER=openai_compatible
    FATTY_LLM_BASE_URL=http://localhost:11434/v1   # Ollama default; adjust for LM Studio / vLLM
    FATTY_LLM_MODEL=<your loaded model name>
    # No FATTY_LLM_API_KEY needed — local runtimes don't authenticate
    ```
    This uses the OpenAI Chat Completions wire format exposed by these local runtimes, with no key and no per-token billing.
  - **API key providers:** for OpenAI or Anthropic, set `FATTY_LLM_PROVIDER`, `FATTY_LLM_API_KEY`, and `FATTY_LLM_MODEL`.
- **USDA FDC:** set `FATTY_FDC_API_KEY` with your free data.gov key. Omit to skip generic-food lookups.
- **Open Food Facts:** enabled by default (no key needed). Set `FATTY_OFF_ENABLED=false` to disable.
- **Brave Search:** set `FATTY_SEARCH_API_KEY` and `FATTY_SEARCH_ENABLED=true`. Disabled by default.

See `.env.example` for all available options with documentation.

**5a. (Required if using `claude_code` provider) One-time Claude Code login:**

The `claude_code` provider authenticates through your own Claude Code session. The Claude Code CLI is pre-installed in the backend image; you only need to log in once. The session is stored in a named Docker volume (`claude-config`) and survives `docker compose down && up` without re-login.

After starting the stack for the first time:

```sh
# Open an interactive login session in the running api container:
docker compose exec api claude login
```

Claude Code prints a URL. Open it in your browser, authorize, and paste the device code back into the terminal. The session is written into the `claude-config` volume and shared automatically with the `worker` container.

To verify the session is active:

```sh
curl -fsS http://localhost:8000/healthz/sources | python3 -m json.tool
# Look for: {"id": "claude_code", "enabled": true, "available": true, ...}
```

**Security note:** the `claude-config` Docker volume contains your OAuth session credentials. It is a host secret — never copy its contents into the image, never commit it to source control, and restrict its host-path permissions if you bind-mount it. The image itself contains only the Claude Code binary; no credentials are baked in.

**6. Start the stack:**

```sh
docker compose up
```

Docker Compose builds the backend image, runs first-boot Alembic migrations
automatically (the `migrate` service completes before the API starts), then
brings up all four services.

**7. Confirm health:**

```sh
curl -fsS http://localhost:8000/healthz
# {"status":"ok"}

curl -fsS http://localhost:8000/healthz/sources
# {"sources":[...]}  lists enabled/available evidence sources
```

A 200 response from `/healthz` confirms the API is up. `/healthz/sources` shows
which evidence sources are enabled and available — useful to verify your provider
configuration without making any estimation calls.

### Provider Availability

Every optional provider (LLM, USDA FDC, OFF, Brave Search) can be omitted.
The app starts and serves health with all providers unconfigured; estimation
degrades to model-prior-with-status rather than failing. Source availability is
reflected in `GET /healthz/sources`.

### First-Boot Migrations

Alembic migrations run automatically on first `docker compose up` via the
`migrate` service. The API and worker do not start until migrations complete, so
the schema is always ready from a clean checkout.

To apply migrations manually (e.g. after a code update):

```sh
docker compose run --rm migrate
```

### Stopping and Cleaning Up

```sh
docker compose down           # stop and remove containers
docker compose down -v        # also drop the postgres data volume
```

## Development

The monorepo is laid out as `backend/` (FastAPI), `mobile/` (Expo / React
Native), and `contracts/` (shared contract code), with documentation in `docs/`.
See `docs/architecture/repo-layout.md` for the layout and verification contract.

Run the current repository checks:

```sh
make verify
```

`make verify` is the single entry point: it runs repository governance and then
each package's verification hook — ruff, mypy, and pytest for the backend;
TypeScript, ESLint, and Jest for mobile.

See `docs/operations/local-dev-stack.md` for the service contract and details.

## Contributing

See `CONTRIBUTING.md`, `AGENTS.md`, and `docs/operations/branching-and-prs.md`.

## License

The project is intended to be open source. A license has not been formally selected yet; self-hosting for personal use is encouraged in the meantime.


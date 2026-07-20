# Slacks

Slacks is an iOS-first, open source calorie and macro tracker for people who hate traditional tracking. Users describe what they ate or did in natural language, and Slacks turns that into structured, editable food and exercise entries with evidence and assumptions.

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

Slacks is designed for self-hosting. The Docker Compose stack brings up Postgres,
Redis, the FastAPI API, and a Celery worker over plain HTTP from a clean checkout.

**Scope:** local self-host, plain HTTP by default. For encrypted transport on
your private tailnet, the supported paved path is HTTPS on port 443 via
`tailscale serve` — see [HTTPS over Tailscale](#https-over-tailscale-optional)
below. Public-internet ingress, production hardening, resource limits, backups,
and cloud/Kubernetes deployment are intentionally out of scope.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- A USDA FoodData Central API key (free, from [fdc.nal.usda.gov/api-guide](https://fdc.nal.usda.gov/api-guide)) if you want generic-food USDA nutrition lookups — optional; the app runs without it
- An LLM API key, a local model runtime, or a first-party CLI login (Claude Code
  or Codex) for full estimation quality — optional; the app starts and serves
  health with the built-in `fake` provider

### Step-by-Step Bring-Up

**1. Clone and enter the repo:**

```sh
git clone https://github.com/epurn/slacks.git
cd slacks
```

**2. Copy the environment template:**

```sh
cp .env.example .env
```

**3. Generate and set the auth secret** (required before first boot):

```sh
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Open `.env` and replace the `SLACKS_AUTH_SECRET` placeholder with the output.
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
- **LLM:** set `SLACKS_LLM_PROVIDER`. Leave `SLACKS_LLM_PROVIDER=fake` to skip (estimation degrades gracefully).
  - **Claude subscription (no API key):** if you have a Claude monthly plan, the `claude_code` provider runs estimation through your own subscription — no per-token billing:
    ```
    SLACKS_LLM_PROVIDER=claude_code
    # SLACKS_LLM_MODEL is optional — Claude Code uses your plan's model by default
    # No SLACKS_LLM_API_KEY — auth is your 'claude login' session (see step 7 below)
    # Required for nutrition-label scanning (defaults to false, fails closed):
    SLACKS_LLM_SUPPORTS_VISION=true
    ```
    See **Claude Code session setup** (step 7) to complete the one-time login.
  - **Codex CLI:** if you use Codex through ChatGPT or an enterprise access token, the `codex` provider runs estimation through the first-party Codex CLI installed in the backend image:
    ```
    SLACKS_LLM_PROVIDER=codex
    # SLACKS_LLM_MODEL is optional — set it for reproducible deployments
    # Leave SLACKS_LLM_BASE_URL unset; Codex is not an HTTP base-URL provider
    # Optional for image-capable Codex models:
    # SLACKS_LLM_SUPPORTS_VISION=true
    ```
    See **Codex session setup** (step 8) to complete the one-time login. If you prefer API-key auth, set `SLACKS_LLM_API_KEY` instead; Slacks passes it only to the `codex exec` child as `CODEX_API_KEY`.
  - **Zero-cost local model:** run [Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai), or [vLLM](https://github.com/vllm-project/vllm) locally, then set:
    ```
    SLACKS_LLM_PROVIDER=openai_compatible
    SLACKS_LLM_BASE_URL=http://localhost:11434/v1   # Ollama default; adjust for LM Studio / vLLM
    SLACKS_LLM_MODEL=<your loaded model name>
    # No SLACKS_LLM_API_KEY needed — local runtimes don't authenticate
    ```
    This uses the OpenAI Chat Completions wire format exposed by these local runtimes, with no key and no per-token billing.
  - **API key providers:** for OpenAI or Anthropic, set `SLACKS_LLM_PROVIDER`, `SLACKS_LLM_API_KEY`, and `SLACKS_LLM_MODEL`.
- **USDA FDC:** set `SLACKS_FDC_API_KEY` with your free data.gov key. Omit to skip generic-food lookups.
- **Open Food Facts:** enabled by default (no key needed). Set `SLACKS_OFF_ENABLED=false` to disable.
- **Official-source search:** enabled by default via the bundled keyless `searxng` service — no key or setup needed. To use Brave instead, set `SLACKS_SEARCH_PROVIDER=brave` and `SLACKS_SEARCH_API_KEY`; set `SLACKS_SEARCH_PROVIDER=none` to turn search off.

See `.env.example` for all available options with documentation.

**6. Start the stack:**

```sh
docker compose up
```

Docker Compose builds the backend image, runs first-boot Alembic migrations
automatically (the `migrate` service completes before the API starts), then
brings up all services (Postgres, Redis, the API, the Celery worker, and the
private `searxng` search service).

**7. (Required if using `claude_code` provider) One-time Claude Code login:**

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

**8. (Required if using `codex` provider without `SLACKS_LLM_API_KEY`) One-time Codex login:**

The `codex` provider authenticates through Codex CLI state under `CODEX_HOME`.
The Codex CLI is pre-installed in the backend image. The session is stored in a
named Docker volume (`codex-config`) mounted at `/codex-config` and shared by
`api` and `worker`, so it survives `docker compose down && docker compose up`
without re-login.

After starting the stack for the first time, use one of these setup paths:

```sh
# Browser login in the running api container:
docker compose exec api codex login

# Headless/device-code login:
docker compose exec api codex login --device-auth

# Enterprise/access-token login, using a token from your secret manager:
printf '%s' "$CODEX_ACCESS_TOKEN" | docker compose exec -T api codex login --with-access-token
```

For API-key auth, skip saved login and set `SLACKS_LLM_API_KEY` in `.env`.
The adapter maps that value only to the `codex exec` child process as
`CODEX_API_KEY`; do not set `CODEX_API_KEY` globally in `.env`.

To verify the session or API-key path is visible without making an estimation
call:

```sh
curl -fsS http://localhost:8000/healthz/sources | python3 -m json.tool
# Look for: {"id": "codex", "enabled": true, "available": true, ...}
```

**Security note:** the `codex-config` Docker volume may contain `auth.json`
access tokens, sessions, logs, and other Codex state. It is a host secret: never
copy it into the image, never commit it, never include it in support artifacts,
and restrict host-path permissions if you bind-mount it. The image itself
contains only the Codex CLI/runtime; no Codex credentials are baked in.

**9. Confirm health:**

```sh
curl -fsS http://localhost:8000/healthz
# {"status":"ok"}

curl -fsS http://localhost:8000/readyz
# {"status":"ready"}

curl -fsS http://localhost:8000/healthz/sources
# {"sources":[...]}  lists enabled/available evidence sources
```

A 200 response from `/healthz` confirms the API is up. `/readyz` returns 200 when the database is ready, or 503 if it is unavailable — useful for orchestration and health checks. `/healthz/sources` shows which evidence sources are enabled and available — useful to verify your provider configuration without making any estimation calls.

**Testing in an iOS simulator?** Run `make sim-smoke` first. It confirms the
stack is coherent (backend images from one checkout, Alembic at head, health
green) and prints the exact connect-screen URL derived from your `.env`
`API_PORT`. See [Local Development Stack → Simulator Readiness Smoke](docs/operations/local-dev-stack.md#simulator-readiness-smoke-fty-250).

### HTTPS over Tailscale (Optional)

To reach the backend from your other devices with **encrypted transport**, serve
it over your tailnet: `tailscale serve` terminates TLS on the standard port 443
with a valid certificate for the host's MagicDNS name and reverse-proxies to the
loopback-bound API port. The app then connects to
`https://<host>.<tailnet-name>.ts.net` — no high port in the URL, no cleartext
reachable off-box, and the endpoint stays private to your own tailnet (serve,
never funnel). Setup, prerequisites (MagicDNS + HTTPS certificates), the
one-line `.env` switch (`API_BIND_HOST=127.0.0.1`), and verification steps are
in [HTTPS over Tailscale](docs/operations/tailscale-https.md); or run
`make tailscale-serve`.

### Provider Availability

Every optional provider (LLM, USDA FDC, OFF) can be omitted, and official-source
search runs keyless by default via the bundled `searxng` service. The app starts
and serves health with all providers unconfigured; estimation degrades to
model-prior-with-status rather than failing. Source availability is reflected in
`GET /healthz/sources`.

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

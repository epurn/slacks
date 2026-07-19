# Local Development Stack

The repo-root `docker-compose.yml` (FTY-011, self-host setup FTY-072) brings up
the full local backend stack over plain HTTP:

```sh
cp .env.example .env           # copy template; set SLACKS_AUTH_SECRET
docker compose up              # starts all services; migrations run first
```

For the full self-host walkthrough (prerequisites, provider config, first-boot
checklist, smoke check) see the README **Self-Hosting** section. To reach the
stack over **HTTPS on port 443 across your tailnet** (encrypted transport,
valid certificate, no high port in the URL) see
[HTTPS over Tailscale](tailscale-https.md) (FTY-367).

## Services

| Service | Image / build | Purpose | Host port |
| --- | --- | --- | --- |
| `postgres` | `postgres:16.4-alpine` | Application database. | — (internal only) |
| `redis` | `redis:7.4-alpine` | Celery broker / result backend. | — (internal only) |
| `migrate` | `./backend` (Alembic) | One-shot first-boot migration runner. | — |
| `api` | `./backend` (FastAPI) | HTTP API; serves `GET /healthz` (liveness), `GET /readyz` (readiness — checks DB), and `GET /healthz/sources`. | `${API_PORT:-8000}` |
| `worker` | `./backend` (Celery) | Background estimation worker. | — |
| `searxng` | `searxng/searxng` (pinned) | Private, keyless metasearch backing the official-source search adapter (FTY-164/165). | — (internal only) |

- Postgres and Redis are **not published to host interfaces by default** (FTY-109).
  The `api`, `worker`, and `migrate` services reach them over the internal compose
  network by service name (`postgres`, `redis`). This removes an unauthenticated
  Redis and Postgres exposure from the self-host box's LAN. To re-enable direct
  host access (e.g. for a DB GUI or local `psql`), add a loopback-only mapping to
  the relevant service in `docker-compose.yml`:
  ```yaml
  ports:
    - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"   # postgres
    - "127.0.0.1:${REDIS_PORT:-6379}:6379"       # redis
  ```
  Alternatively, access the database without a host port via:
  ```sh
  docker compose exec postgres psql -U slacks slacks
  ```
- `api`, `worker`, `postgres`, and `redis` all declare `restart: unless-stopped`;
  they restart automatically if they crash. The one-shot `migrate` service has no
  restart policy and exits after applying migrations.
- Postgres and Redis define healthchecks (`pg_isready`, `redis-cli ping`).
- The `migrate` service runs `alembic upgrade head` once and exits; it depends on
  `postgres` being healthy. The `api` and `worker` services depend on `migrate`
  completing successfully before they start.
- The API healthcheck polls its own `GET /healthz` and expects HTTP 200.
- The worker healthcheck runs `celery inspect ping` against the configured
  `app.worker:celery_app` to confirm the worker is alive and connected to Redis.
- Images for Postgres, Redis, and SearXNG are pinned to exact tags per the
  security baseline's pinned-dependency principle.
- `searxng` runs a private [SearXNG](https://docs.searxng.org/) metasearch
  instance that backs the official-source search adapter (FTY-164). It is
  **keyless** and **enabled by default**, so search works out of the box — no
  Brave API key required. Like Postgres and Redis it is **not published to the
  host** (FTY-165); the `api` and `worker` reach it over the internal compose
  network at `http://searxng:8080`. The backend sends only sanitized
  item-identity queries — never any personal context. Its minimal config lives in
  `searxng/settings.yml` (mounted read-only at `/etc/searxng`), which enables the
  JSON output format the adapter consumes and sets a documented **non-secret dev
  placeholder** secret key. Exposing SearXNG to the host or the public internet is
  out of scope and would need a separate, explicit operator story. Search
  degrades gracefully (model-prior-with-status) when the service is unreachable,
  so `api`/`worker` do not hard-depend on it starting.
- The `backend/` image includes a pinned Node.js runtime, the Claude Code CLI
  (`claude`), and the Codex CLI (`codex`) so the `api` and `worker` services can
  use the first-party local CLI LLM providers without mounting host binaries.

## Volumes

| Volume | Mounted at | Purpose |
| --- | --- | --- |
| `postgres-data` | `/var/lib/postgresql/data` | Postgres data. Persists across restarts. |
| `claude-config` | `/claude-config` (api + worker) | Claude Code session / config dir (FTY-088). |
| `codex-config` | `/codex-config` (api + worker) | Codex CLI state / session dir (`CODEX_HOME`, FTY-296). |

The `claude-config` volume is populated once by `claude login` (see **Claude Code
login** below) and persists the OAuth session so subsequent `docker compose down &&
up` cycles do not require re-login. Treat it as a **host secret**: never copy its
contents into the image or commit them. `CLAUDE_CONFIG_DIR=/claude-config` is
fixed in the compose `environment:` block for both `api` and `worker`.

The `codex-config` volume is populated once by `codex login`,
`codex login --device-auth`, or `codex login --with-access-token` (see
**Codex login** below) and persists Codex state so subsequent `docker compose
down && up` cycles do not require re-login. Treat it as a **host secret**: it may
contain `auth.json` access tokens, sessions, logs, and other Codex state. Never
copy it into the image, commit it, or include it in support artifacts.
`CODEX_HOME=/codex-config` is fixed in the compose `environment:` block for both
`api` and `worker`.

## Configuration

Configuration comes from `.env` (copied from `.env.example`). `.env.example` is
the documented self-host configuration contract (FTY-072): it lists every
required and optional `SLACKS_*` variable with documentation and placeholder-only
values. The real `.env` is gitignored; never commit real secrets.

Key variable groups (see `.env.example` for full documentation):

| Group | Variables | Notes |
| --- | --- | --- |
| Auth | `SLACKS_AUTH_SECRET`, `SLACKS_AUTH_TOKEN_TTL_SECONDS` | Auth secret is required; generate before first boot. |
| Datastores | `POSTGRES_*`, `SLACKS_DATABASE_URL`, `REDIS_PORT`, `SLACKS_REDIS_URL` | Service hostnames must match compose service names. |
| Host ports | `API_PORT`, `API_BIND_HOST` | Published host port for the API; containers always listen on fixed ports. `API_BIND_HOST` is optional: unset publishes on all interfaces (the local-dev default); `127.0.0.1` is the tailnet-served posture ([HTTPS over Tailscale](tailscale-https.md)). `POSTGRES_PORT` / `REDIS_PORT` are meaningful only if you re-enable loopback-only host mappings for direct datastore access (see Services above). |
| Application | `SLACKS_ENVIRONMENT`, `SLACKS_LOG_LEVEL` | App config. |
| LLM provider | `SLACKS_LLM_*` | Optional; defaults to `fake` (model-prior-with-status). See LLM providers below. |
| Estimator policy | `SLACKS_ESTIMATOR_*` | Optional estimate-vs-ask clarification policy; defaults to estimate-first and does not change privacy/logging/provider validation rules. |
| USDA FDC | `SLACKS_FDC_*` | Optional; free data.gov key. Disabled when key absent. |
| Open Food Facts | `SLACKS_OFF_*` | Optional, open API; enabled by default, no key required. |
| Search | `SLACKS_SEARCH_*` | Keyless SearXNG by default (points at the `searxng` service; enabled, no key). Brave is an opt-in override; `none` turns search off. |

## LLM Providers

The `SLACKS_LLM_PROVIDER` variable selects the LLM backend. It defaults to `fake`
(no network calls; estimation degrades to model-prior-with-status). CLI-session
and local-runtime options are available for self-hosters who want live estimation
without an API key:

### `claude_code` — Claude subscription, no per-token billing

Set in `.env`:
```
SLACKS_LLM_PROVIDER=claude_code
# SLACKS_LLM_MODEL is optional — Claude Code picks the model from your plan
# No SLACKS_LLM_API_KEY — auth is the operator's 'claude login' session
```

Then complete the **one-time Claude Code login** (see below).

### `codex` — Codex CLI login or child-only API key

Set in `.env`:
```
SLACKS_LLM_PROVIDER=codex
# SLACKS_LLM_MODEL is optional — set it for reproducible deployments
# SLACKS_LLM_SUPPORTS_VISION=true only for image-capable Codex models
# No SLACKS_LLM_BASE_URL — Codex is not an HTTP base-URL provider
```

Then complete the **one-time Codex login** (see below). As an alternative, set
`SLACKS_LLM_API_KEY` for the Codex provider; the adapter maps it only to the
`codex exec` child process as `CODEX_API_KEY` for that invocation. Do not add a
global `CODEX_API_KEY` to `.env`.

### `openai_compatible` — Local model runtime (Ollama / LM Studio / vLLM)

Set in `.env`:
```
SLACKS_LLM_PROVIDER=openai_compatible
SLACKS_LLM_BASE_URL=http://localhost:11434/v1   # Ollama default; adjust for LM Studio / vLLM
SLACKS_LLM_MODEL=<your loaded model name>
# No SLACKS_LLM_API_KEY needed — local runtimes don't authenticate
```

## Claude Code Login (One-Time Setup, FTY-088)

The `claude_code` provider requires a one-time interactive login to establish a
Claude Code session. The session is written into the `claude-config` Docker volume
and shared between `api` and `worker`, so it survives restarts without re-login.

**Prerequisites:** the stack must be running (`docker compose up -d`) and
`SLACKS_LLM_PROVIDER=claude_code` must be set in `.env`.

```sh
# Run the login flow in the api container (interactive — needs a terminal):
docker compose exec api claude login
```

Claude Code prints a URL. Open it in your browser, authorize with your Claude
account, and paste the device code back into the terminal. The session is written
to `/claude-config` inside the container (the `claude-config` volume).

To confirm the session persists across restarts:

```sh
docker compose down && docker compose up -d
curl -fsS http://localhost:8000/healthz/sources | python3 -m json.tool
# Expect: {"id": "claude_code", "enabled": true, "available": true, ...}
```

**Security:** the `claude-config` volume contains OAuth credentials. Never bind-mount
it to a path with loose permissions, never copy its contents into the image, and
never commit it. The image contains only the Claude Code binary — no credentials.

## Codex Login (One-Time Setup, FTY-296)

The `codex` provider uses the first-party Codex CLI installed in the backend
image. By default it authenticates through saved Codex state under `CODEX_HOME`;
the compose stack sets `CODEX_HOME=/codex-config` and mounts the same
`codex-config` volume into `api` and `worker`.

**Prerequisites:** the stack must be running (`docker compose up -d`) and
`SLACKS_LLM_PROVIDER=codex` must be set in `.env`. Leave `SLACKS_LLM_BASE_URL`
unset for this provider. `SLACKS_LLM_MODEL` is optional but recommended for
reproducible deployments, and `SLACKS_LLM_SUPPORTS_VISION=true` is required before
image-capable Codex models receive image inputs.

Use one of these saved-auth flows in the `api` container:

```sh
# Browser login:
docker compose exec api codex login

# Headless/device-code login:
docker compose exec api codex login --device-auth

# Enterprise/access-token login, using a token from your secret manager:
printf '%s' "$CODEX_ACCESS_TOKEN" | docker compose exec -T api codex login --with-access-token
```

`CODEX_ACCESS_TOKEN` is only an operator setup input for seeding Codex auth into
`CODEX_HOME`; it is not a Slacks configuration variable. For API-key auth instead
of saved login, set `SLACKS_LLM_API_KEY` in `.env`. The Slacks adapter maps that
value only to the `codex exec` child process as `CODEX_API_KEY`; do not set
`CODEX_API_KEY` globally in `.env`.

Confirm the provider is selected and locally available without making an
estimation call:

```sh
curl -fsS http://localhost:8000/healthz/sources | python3 -m json.tool
# Expect: {"id": "codex", "enabled": true, "available": true, ...}
```

Optional live provider smoke, after login or with a one-command `CODEX_API_KEY`
injection from your secret manager:

```sh
docker compose exec -T api sh <<'SH'
cat >/tmp/slacks-codex-smoke.schema.json <<'JSON'
{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":false}
JSON
printf 'Return {"ok": true} as JSON only.\n' \
  | codex exec - --output-schema /tmp/slacks-codex-smoke.schema.json
rm -f /tmp/slacks-codex-smoke.schema.json
SH
```

This smoke uses a neutral synthetic prompt and tiny schema; it never sends diary
text. Do not require live Codex in CI.

**Security:** the `codex-config` volume may contain `auth.json` access tokens,
sessions, logs, and other Codex state. Never bind-mount it to a path with loose
permissions, never copy its contents into the image, never commit it, and never
include it in support artifacts. The image contains only the Codex CLI/runtime —
no credentials.

## Verifying

```sh
docker compose up -d
curl -fsS http://localhost:8000/healthz          # -> {"status":"ok"} — liveness (process-up, no DB)
curl -fsS http://localhost:8000/readyz           # -> {"status":"ready"} — readiness (200 DB reachable / 503 not ready)
curl -fsS http://localhost:8000/healthz/sources  # -> provider capability list
docker compose ps                                # migrate exited 0, api/postgres/redis/worker/searxng all healthy
docker compose down                              # add -v to drop all volumes
```

`GET /healthz/sources` lists each evidence source (LLM, FDC, OFF, search) with
its `enabled` and `available` flags, so you can confirm provider configuration
without making any estimation calls. With the default keyless SearXNG search
(FTY-165) the `official_source` entry reports both `enabled: true` and
`available: true` out of the box — no API key needed:

```sh
curl -fsS http://localhost:8000/healthz/sources | python3 -m json.tool
# official_source: {"enabled": true, "available": true, ...}
# (available reflects config, not a live probe: it is true whenever the searxng
#  provider is selected. Confirm the container itself is up with `docker compose ps`.)
```

Selecting Brave without a key, or setting `SLACKS_SEARCH_PROVIDER=none` /
`SLACKS_SEARCH_ENABLED=false`, flips these flags so the opt-out or missing
credential is visible here. The `claude_code` entry specifically shows whether
the CLI is installed and the session is valid; the `codex` entry shows whether
the CLI is installed and either a saved auth marker under `CODEX_HOME` or
`SLACKS_LLM_API_KEY` is configured while `SLACKS_LLM_PROVIDER=codex`. These
descriptors expose booleans only — no credential contents, identity, host path,
filename content, or raw CLI output.

## Simulator Readiness Smoke (FTY-250)

Before testing Slacks in an iOS simulator, run one command to confirm the stack is
actually *ready* — not just serving `/healthz`. A stack can be healthy at the
process level yet fail the app later: backend images built from different
checkouts, Postgres behind the code's Alembic head, or a simulator pointed at the
wrong port. The smoke catches exactly those drifts and prints the connect URL.

```sh
docker compose up -d          # bring the stack up first
make sim-smoke                # read-only readiness report (prints no secrets)
```

`make sim-smoke` runs `python -m app.ops.sim_readiness` in the backend uv
environment. It is **read-only** — it detects drift and prints the fix path but
never rebuilds, migrates, or restarts anything for you — and it **never prints
secret values** (auth secret, DB password, provider keys, tokens, session
material). It reports:

- **Backend image coherence.** `api`, `worker`, and `migrate` all build from
  `./backend`, so a coherent stack resolves them to one image id. Divergent ids
  mean one was rebuilt from a different checkout than the others (the
  2026-07-05 failure mode) — the smoke flags it as image DRIFT.
- **Alembic drift.** It reads the running database's `alembic_version` (via
  `docker compose exec postgres`, so no host port is needed) and compares it to
  the code head read from `backend/alembic/versions/`. It prints **both**
  versions and fails when the database is behind (e.g. DB `0016` while code
  expects `0017`).
- **API health.** `GET /healthz` (liveness), `GET /readyz` (DB readiness), and
  `GET /healthz/sources` (evidence-source capabilities, including the active LLM
  provider — booleans only, no key values).
- **Worker health.** It pings the Celery worker with the same
  `celery -A app.worker:celery_app inspect ping` the compose healthcheck uses
  (over `docker compose exec`, so no host port is needed) and fails when no
  worker pongs back. The HTTP probes only reach the API; a stopped or wedged
  worker serves no endpoint yet would leave estimator jobs stuck later, so the
  smoke will **not** print READY until the worker answers.
- **The simulator connect URL**, derived from `.env` `API_PORT`:
  `http://localhost:<API_PORT>`. With `API_PORT=18000` this is
  `http://localhost:18000`. This is the value to enter on the app's connect
  screen — **not** the mobile code's `localhost:8000` fallback, which is only
  correct when `API_PORT` is left at its default.

When the smoke reports drift, the coherent fix path (also printed by the command)
rebuilds the backend images from the current checkout, migrates to head, and
restarts the API and worker on the new image:

```sh
docker compose build api worker migrate   # rebuild from this checkout
docker compose run --rm migrate            # apply Alembic to head
docker compose up -d api worker            # restart on the new image
make sim-smoke                             # re-run until READY
```

### Connecting the simulator

A **fresh simulator install has no persisted connected server** — the app resolves
its API base URL from the on-device connection store, which starts empty
(`mobile/api/config.ts`). So the first-run flow is:

1. `docker compose up -d` and `make sim-smoke` until it reports **READY**.
2. Launch the app in the simulator.
3. On the connect screen, enter the printed URL (e.g. `http://localhost:18000`).
4. Sign in or create an account.

You must connect to the printed URL **before** sign-in; there is no persisted
server to fall back to on a fresh install.

### Live backend vs. hermetic E2E mock

`make sim-smoke` and the connect flow above target the **real local backend** —
the Docker Compose stack this document describes, published on `.env`'s
`API_PORT` (e.g. `http://localhost:18000`). This is the live v1 target: your
requests hit FastAPI, Postgres, the worker, and the configured providers.

That is **not** the same simulator mode `mobile/verify-e2e.sh` runs. The E2E
suite builds the app with `EXPO_PUBLIC_SLACKS_E2E=true` baked in, which installs
an **in-process mock `fetch`** (see `mobile/e2e/launchMode.ts`) so no request
ever leaves the app. In that mode the app's server URL is the synthetic
`E2E_SERVER_URL = 'http://localhost:8000'` in `mobile/e2e/fixtures.ts` — it is a
hermetic placeholder that is only ever *matched* by the mock, never *connected*
to. Nothing listens there, and it is **deliberately unrelated** to the live
stack's `API_PORT`.

So do not read that `localhost:8000` as the live v1 backend: when `.env`
publishes `API_PORT=18000`, the real target is `http://localhost:18000` (what
`make sim-smoke` prints), while `localhost:8000` in the E2E fixtures is a mocked
constant that never touches the network. Use the printed smoke URL for live
simulator testing; use `mobile/verify-e2e.sh` only for the hermetic Maestro
suite.

## Food Dogfood Smoke (FTY-256)

After the stack is **ready** (`make sim-smoke` prints READY) and a **real LLM
provider** is configured, run one command to prove v1 **food logging actually
works on the live local backend** — before a human opens the simulator:

```sh
docker compose up -d          # stack up
make sim-smoke                # confirm READY first
make food-smoke               # live food dogfood smoke (prints no secrets)
```

`make food-smoke` runs `python -m app.ops.food_dogfood_smoke` in the backend uv
environment. It logs in to a **reused throwaway local account** (a fixed fixture
email, a non-secret fixture password), registering that account only on the
first run so repeat runs never trip the backend's register rate limiter (default
5/IP/hour); it then submits a small set of representative food logs to the live
API at `http://localhost:${API_PORT}`, waits for each event to reach a terminal
estimation state, and prints a sanitized pass/fail summary — per-item source
type/ref and calories, and any clarification text.

It catches the exact v1 dogfood regressions the hermetic suites cannot see (the
2026-07-10 live failure was a clarify the fixture suites never triggered). The
representative fixtures and what each proves:

| Fixture | Asserted live outcome |
| --- | --- |
| `compliments brand chicken strips (i had 4)` | Completes; a **branded** item resolves through the branded/reference/model tiers, **not** a generic USDA/FDC row (the `Compliments` → `DENNY'S` mis-match). |
| `one banana` | Completes; costs as fresh banana, **not** dehydrated/powdered banana (a plausible calorie band is the detector). |
| `2 large eggs` | Completes; a supplied count resolves — no generic quantity clarification. |
| `1 slice wheat toast` | Completes; a stated slice resolves. |
| `two scrambled eggs and one slice buttered toast` | Completes with **two** derived items, each costed with honest provenance and inside its **own** plausible calorie band (eggs and toast are banded separately). |
| `100 grams banana` | Completes; measured amount resolves; not banana powder. |
| `4 toppables brand crackers with 1tbsp of loblaws store brand (PC/presidents choice) dill pickle hummus` | The 2026-07-10 live failure — completes with **two** derived items (no `needs_clarification`, no `failed`), each inside its **own** plausible calorie band (crackers and hummus are banded separately, so a bad split cannot hide behind a passing total) with honest source/provenance. |
| `made good mornings - chocolate chip organic soft baked oat bars, 1 serving` | Completes; a stated serving is a usable portion (never `needs_clarification`), and does **not** resolve via a `model_prior`/`user_text` shortcut. |

The FTY-373 **never-fail** regression fixtures pin the 2026-07-16 live-dogfood
failures where informal/homemade/consumable food or infra trouble came back
terminal `failed`. They carry `never_fail: true`: the fixture only has to reach a
terminal **non-**`failed` estimate — a rough degraded `completed` or a
`partially_resolved` passes, but terminal `failed` (a deadline/budget/transient
breach surfaced as a failed entry) and a reflexive `needs_clarification` do not.
Their calorie bands are wide rough-estimate plausibility tolerances (the coarse
degrade prior costs an unresolvable serving at ~200 kcal, so a band spans both a
good live estimate and that rough fallback), never a nutrition table.

| Never-fail fixture | Asserted live outcome |
| --- | --- |
| `homemade banh mi on a brioche style bun … and 3 ground pork meat` | The exact 2026-07-16 phrase that failed ×3 (`run_wall_clock_deadline_exceeded`, then `provider_transient_error`) → a rough, honestly-labelled estimate, **at least one** item, never terminal `failed`. |
| `nicorette 4mg gum` / `nicorette brand gum` | The consumable pair — recognized and estimated (`nicorette 4mg gum` was previously `unparseable_input`), never `failed`. |
| `a big bowl of the chicken and rice casserole i threw together last night …` / `some leftover thrown together veggie curry i made …` | Adversarial thrown-together assemblies of unbranded ingredients → recognized and estimated, never terminal `failed`. |

For every strict (non-never-fail) fixture the smoke also asserts that a log
carrying a count or measured amount **never** produces a generic no-option
quantity clarification, and that each completed item carries a source/provenance
status with positive calories (a silent zero is not an acknowledgement).

### Prerequisites

- The stack is **up and migrated** (`make sim-smoke` reports READY).
- A **real LLM provider** is configured and logged in (`SLACKS_LLM_PROVIDER` set
  to `claude_code`, `codex`, or `openai_compatible`, per the **LLM Providers**
  and login sections above). The default `fake` provider degrades estimation to
  model-prior-with-status and **cannot parse** natural-language food, so the
  smoke will report failures against it — that is expected, not a v1 regression.
- Live evidence sources help the branded fixtures resolve with the best
  provenance: the keyless SearXNG search (default) and Open Food Facts are on out
  of the box; USDA FDC needs `SLACKS_FDC_API_KEY` (optional). Confirm provider
  wiring with `curl -fsS http://localhost:${API_PORT}/healthz/sources`.

### Interpreting results

- **Exit 0, `PASS: all N fixtures …`** — every fixture reached the expected v1
  behavior. Food logging is usable; open the simulator.
- **Exit nonzero, `FAIL: …`** — read the `!` lines under each failed fixture.
  Because this is the **live** backend, a failure is a real v1 dogfood
  regression *or* a stack/provider not configured for live estimation. Common
  causes:
  - **API unreachable** (`cannot reach the local API …`) — the stack is down or
    on a different `API_PORT`; run `docker compose up -d` and `make sim-smoke`.
  - **Registration/submit HTTP error** — the stack may be unmigrated or
    unhealthy; re-run `make sim-smoke` and apply its coherent fix path.
  - **`needs_clarification` on a counted entry** — a live clarify regression
    (the FTY-252/253/254 estimate-first boundary); the sanitized question text is
    printed under the fixture.
  - **`forbidden source` / calorie band** — a branded item matched a generic FDC
    row, or a banana costed as powder — the exact regressions this smoke guards.
  - **`per-item plausible band` / `no derived item matched expected item`** — a
    multi-item entry produced a bad split: one item costed implausibly low/high
    even though the entry **total** looked fine, or an expected item (e.g. the
    hummus) never appeared as its own derived item.
  - **`never-fail invariant forbids …` / `must be estimated, not clarified/failed`**
    — a never-fail fixture (informal/homemade/consumable phrase) came back
    terminal `failed` (a deadline/budget/transient breach surfaced as a failed
    entry) or as a reflexive `needs_clarification` instead of a rough estimate —
    the FTY-370/371/372 never-fail contract regressed.

### Live-local vs. hermetic E2E

This smoke targets the **live local backend** (real FastAPI, Postgres, worker,
and the configured evidence/LLM providers) on `.env`'s `API_PORT`, exactly like
`make sim-smoke` and the simulator connect flow. It is **not** the hermetic
`mobile/verify-e2e.sh` mode, whose in-process mock `fetch` never leaves the app
and whose `localhost:8000` is a synthetic constant (see **Live backend vs.
hermetic E2E mock** above). Because it depends on live external providers, it is
**not** part of `make verify` and must never become a required CI gate; only its
pure parsing/assessment/redaction logic is unit-tested
(`backend/tests/test_food_dogfood_smoke.py`).

### Safety

The smoke reuses **one dedicated throwaway account** (a fixed fixture email, a
non-secret fixture password), logging in each run and registering that account
only when it does not exist yet. Reusing a login instead of registering a fresh
account per run is what keeps it safe to run repeatedly: a fresh registration
each run would consume the backend's register rate limiter (default 5/IP/hour)
and make a healthy stack fail with HTTP 429 before any food fixture ran. The
account is dedicated to the smoke and never a real user, so reusing it touches no
real user data. It never prints the bearer token, provider keys, DB passwords,
`.env` contents, or raw provider output — output is built from structured fields
(status, fixture text, source type/ref, calories, sanitized clarification text)
only.

Interpreting the login limiter: if you run the smoke very frequently, the login
rate limiter (default 5 per account / 15 min, 10 per IP / 15 min) can eventually
429 — but that limiter refills every 15 minutes rather than being a hard hourly
registration ceiling, and a `login … failed (HTTP 429)` message is explicit
about the cause, so it is never mistaken for a food regression.

## Container User

The backend image runs all three services (`migrate`, `api`, `worker`) as a
dedicated non-root user — `slacks` (UID/GID 10001) — rather than root (FTY-116).
This limits the blast radius of an in-container exploit to an unprivileged
account. The `claude-config` and `codex-config` volume mountpoints are created
owned by this user so provider login and subsequent session writes succeed
without elevated privileges.

## Out of Scope

Public-internet ingress, production hardening, resource limits, object storage,
and hosted/cloud deployment are intentionally out of scope for this local
self-host stack. Transport encryption on a private tailnet is **in** scope via
the `tailscale serve` paved path — TLS terminated on 443 with a valid tailnet
certificate, proxying to the loopback-bound API port — documented in
[HTTPS over Tailscale](tailscale-https.md) (FTY-367). An in-Compose reverse
proxy / mounted-certificate setup remains out of scope.

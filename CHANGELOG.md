# Changelog

## v1.0.0 — 2026-06-28

First stable release of Fatty, an iOS-first, self-hostable calorie and macro tracker. Users describe meals and exercise in natural language; the backend turns those descriptions into structured, evidence-backed, editable entries.

### Accounts & Profile

- Local auth with HMAC-signed bearer tokens; user registration and login (FTY-020).
- Minimal required profile capture in the mobile app: sex, age, height, current weight, and goal (FTY-021).
- RMR/TDEE target calculator: Mifflin-St Jeor formula variants, NIDDK-style dynamic goal planning, adaptive calibration suggestions (FTY-022).

### Logging Spine

- Natural-language log events with async estimation; entries appear immediately as pending and resolve as the estimator completes (FTY-030).
- Today timeline in the mobile app with live polling, entry status, and evidence icons (FTY-031/FTY-032).
- Async estimation job queue backed by Celery and Redis; pluggable, step-based estimation pipeline (FTY-040).
- Config-driven LLM provider layer supporting OpenAI, Anthropic, and a built-in `fake` provider for offline testing; schema-validated structured completion with vision support (FTY-041/FTY-076).
- Structured parse step: schema-validated candidate extraction, fail-closed routing, and clarification question generation (FTY-042).
- MET-based exercise calculator: curated, versioned MET table; net active calorie calculation; fail-closed routing (FTY-043).

### Estimator & Evidence Sources

- Evidence retrieval contract with explicit source hierarchy and provider-status tracking (FTY-045).
- Generic food calculator: USDA FoodData Central resolution, deterministic serving math, evidence and product caching, SSRF-safe HTTP client (FTY-044).
- Open Food Facts barcode lookup: packaged-product data ranked above USDA generic in the source hierarchy (FTY-060).
- Nutrition label extraction pipeline: structured macro and calorie extraction from uploaded label images (FTY-061).
- Official-source resolution pipeline: Brave Search query, hardened fetch, and LLM extraction for named restaurant and manufacturer items (FTY-062/FTY-079).
- Hardened egress fetcher: HTTPS-only, public-IP enforcement (RFC 1918 and RFC 6598 CGNAT blocked), redirect refusal, per-request size and content-type caps, configurable host allowlist (FTY-078/FTY-081).
- Log attachments table with discard-by-default retention policy (FTY-077).

### Editing & Saved Foods

- Editable food and exercise items on the Today timeline: inline quantity and name corrections with immediate UI feedback (FTY-050).
- Corrections audit trail: immutable correction log with derived-item rescaling (FTY-051).
- Saved foods backend: save endpoint, normalized typeahead matching, object-level authorization (FTY-052).
- Mobile saved-food save action and typeahead suggestion bar for quick re-use of prior entries (FTY-053).

### Evidence Inputs (Mobile)

- Barcode scanner: camera-based scan that triggers an Open Food Facts lookup and populates a log entry (FTY-063).
- Nutrition label capture and upload: camera capture flow that submits label images to the extraction pipeline (FTY-064).

### Weight & Daily Summary

- Weight log backend: time-series body weight entries in canonical kg, object-level authorization (FTY-070).
- Daily totals endpoint: separated intake, target, and burn DTO (FTY-071).
- Mobile weight logging: manual entry input and rolling trend chart (FTY-074).
- Mobile daily summary: calorie and macro totals for the current day (FTY-075).

### Infrastructure & Self-Hosting

- Docker Compose self-host stack: Postgres, Redis, FastAPI, and a Celery worker over plain HTTP from a clean checkout (FTY-011).
- Alembic migrations run automatically on first `docker compose up` via a dedicated `migrate` service; the API and worker do not start until migrations complete (FTY-072).
- `.env.example` template with inline documentation for all `FATTY_*` configuration variables (FTY-072).
- Health endpoints: `GET /healthz` (stack liveness) and `GET /healthz/sources` (per-provider availability and configuration status).
- Egress policy visibility: `GET /healthz/egress` reports the active official-fetch host allowlist.
- **Claude subscription provider** (`FATTY_LLM_PROVIDER=claude_code`): runs estimation through a locally installed Claude Code CLI on the operator's own Claude monthly plan — no API key, no per-token billing. The backend image ships a pinned Claude Code CLI; a one-time `claude login` establishes a session in a persistent Docker volume shared by `api` and `worker` (FTY-087, FTY-088).
- **Keyless local-model provider** (`FATTY_LLM_PROVIDER=openai_compatible`, no `FATTY_LLM_API_KEY`): point Fatty at a local Ollama, LM Studio, or vLLM instance with no API key — the adapter omits the `Authorization` header for keyless local runtimes (FTY-089).
- `GET /healthz/sources` now reports the `claude_code` LLM provider's `enabled`/`available` status so operators can confirm the CLI is installed and the session is valid without making any estimation calls (FTY-088).

### Security

- Adversarial security test suite covering access-control, SSRF boundaries, prompt-injection defences, secret non-disclosure, and query sanitization (FTY-073).
- Threat model and security baseline written and reconciled against the implementation (FTY-073).
- Data retention policy: log attachments discard by default; no unnecessary personal context in provider requests (FTY-077).

---

## Version Sources

The canonical version is set in three places that must match:

| File | Field |
| --- | --- |
| `backend/pyproject.toml` | `[project] version` |
| `mobile/package.json` | `"version"` |
| `mobile/app.json` | `expo.version` (ships as the iOS `CFBundleShortVersionString`) |

To verify consistency:

```sh
grep '^version' backend/pyproject.toml
node -p "require('./mobile/package.json').version"
node -p "require('./mobile/app.json').expo.version"
```

Both must read `1.0.0` for a v1 release.

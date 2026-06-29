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
- Item provenance read-model: visible provenance indicator for each logged item (trusted database, barcode, label scan, saved food, manual correction, or estimate) (FTY-092).
- Provenance-preserving portion adjust: correct item quantities while preserving the original evidence source (FTY-092).
- Item re-match: list alternative evidence sources for a logged item and re-resolve to a chosen source (FTY-093).
- FDC and Open Food Facts evidence clients fail closed on malformed payloads, preventing cascade failures in multi-source resolution (FTY-110).
- LLM rate-limit retry: transient rate limits are retried with jittered exponential backoff; exhaustion fails closed to a plausible estimate (FTY-113).
- LLM provider output hardening: size caps and schema validation prevent malformed or adversarial LLM output from corrupting the estimator (FTY-114).
- Nutrition-fact plausibility bound: reject physically-impossible per-100g macros (e.g., negative values, >100% totals) at the FDC/OFF ingest boundary (FTY-115).

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
- Daily-summary range read endpoint: fetch multi-day calorie and macro totals by date range for trend analysis and historical review (FTY-123).

### Goals & Targets

- Goals backend: create a goal with direction (gain/lose), pace (conservative/moderate/aggressive), and optional target date (FTY-106).
- Target-reveal endpoint: from a direction and pace preset, compute and persist a goal with a derived target and confidence band (FTY-106).
- Manual target override and reset: override the computed target or reset to auto-calculated target with provenance tracking (FTY-095).
- Macro targets: derive protein, carb, and fat targets from the base calorie target using evidence-backed allocation formulas (FTY-094).
- Macro-target provenance: daily-summary read model surfaces macro targets with explicit source attribution (FTY-105).

### Infrastructure & Self-Hosting

- Docker Compose self-host stack: Postgres, Redis, FastAPI, and a Celery worker over plain HTTP from a clean checkout (FTY-011).
- Alembic migrations run automatically on first `docker compose up` via a dedicated `migrate` service; the API and worker do not start until migrations complete (FTY-072).
- `.env.example` template with inline documentation for all `FATTY_*` configuration variables (FTY-072).
- Health endpoints: `GET /healthz` (stack liveness) and `GET /healthz/sources` (per-provider availability and configuration status).
- Egress policy visibility: `GET /healthz/egress` reports the active official-fetch host allowlist.
- **Claude subscription provider** (`FATTY_LLM_PROVIDER=claude_code`): runs estimation through a locally installed Claude Code CLI on the operator's own Claude monthly plan — no API key, no per-token billing. The backend image ships a pinned Claude Code CLI; a one-time `claude login` establishes a session in a persistent Docker volume shared by `api` and `worker` (FTY-087, FTY-088).
- **Keyless local-model provider** (`FATTY_LLM_PROVIDER=openai_compatible`, no `FATTY_LLM_API_KEY`): point Fatty at a local Ollama, LM Studio, or vLLM instance with no API key — the adapter omits the `Authorization` header for keyless local runtimes (FTY-089).
- `GET /healthz/sources` now reports the `claude_code` LLM provider's `enabled`/`available` status so operators can confirm the CLI is installed and the session is valid without making any estimation calls (FTY-088).
- Compose network hardening: Postgres and Redis are no longer exposed to the host; worker container has restart policies and health-check probes (FTY-109).
- Database readiness probe: `/readyz` endpoint waits for Postgres to be ready before reporting the backend as alive (FTY-117).
- Non-root backend container: the API and worker run as a dedicated non-root user `fatty` (UID/GID 10001) for improved container security posture (FTY-116).
- Baseline security headers: production-grade HTTP security headers (HSTS, X-Content-Type-Options, Content-Security-Policy, X-Frame-Options) and interactive API docs gated to localhost-only in production (FTY-112).
- Auth endpoint rate-limiting: per-IP and per-account rate limits on `/login` and `/register` endpoints prevent brute-force attacks (FTY-118).
- Dependabot expansion: Dependabot coverage extended to backend Python, frontend JavaScript, and Docker ecosystem dependencies, with Expo-SDK-specific ignores to prevent breaking changes in SDK-managed mobile code (FTY-108, FTY-121, FTY-125, FTY-126).

### Security

- Adversarial security test suite covering access-control, SSRF boundaries, prompt-injection defences, secret non-disclosure, and query sanitization (FTY-073).
- Threat model and security baseline written and reconciled against the implementation (FTY-073).
- Data retention policy: log attachments discard by default; no unnecessary personal context in provider requests (FTY-077).
- Fail-closed auth boundary: malformed or missing profile data at registration and profile-read boundaries fails closed, preventing invalid state from propagating (FTY-111).
- Weight-entry date validation: weight-entry effective_date is bounded at creation to reject future or absurdly-past entries (FTY-119).

### Mobile UX (v1.0 Redesign)

- Mobile design system: theming, typography, spacing tokens, and reusable component primitives (`Picker`, `Sheet`, `Button`, etc.) for consistent iOS-native appearance and accessibility (FTY-097).
- Today screen redesign: visual refresh with improved typography, spacing, and inline entry editing; evidence icons show provenance at a glance (FTY-098).
- Log entry screen redesign: clearer entry form with food/exercise disambiguation, portion/quantity inputs, and provenance-aware corrections surface evidence sources (FTY-099).
- Correction sheet redesign: edit food/exercise items inline with immediate UI feedback; corrections are immutable and rescaled dependents automatically (FTY-100).
- Trends screen redesign: show smoothed weight trend, macro adherence, and weekly weigh-in reminders with evidence-backed cadence guidance (FTY-101).
- Profile and Settings redesign: grouped settings screen with clear categories and improved mobile usability (FTY-102).
- Offline-queue logging: pending log entries queue locally on the device; sync occurs when connection is restored with idempotent submission (FTY-104).
- Mobile session token store: persist auth tokens securely on the device for session continuity in self-host mode (FTY-090).
- Mobile connect-to-server: URL entry and QR-code scan flow to establish and manage a self-host connection (FTY-107).
- Mobile sign-in / create-account: sign-in and account-creation screens with guided field validation and error recovery for self-host mode (FTY-091).
- Trends adherence: Trends screen consumes the daily-summary range read endpoint to show macro and calorie adherence over configurable date ranges (FTY-124).

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

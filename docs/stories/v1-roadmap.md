# V1 Roadmap

This is the initial story order for Fatty v1. Keep stories small enough for one focused PR.

## Milestone 0: Repository Governance

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-000 | merged | governance | Governance, CI, branch protection, reviewer gate | Main is protected; governance and separate reviewer checks are required. |

## Milestone 1: Project Skeleton

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-010 | merged | contracts | [Monorepo scaffold](FTY-010-monorepo-scaffold.md) | Backend, mobile, shared docs, and root verification commands exist. |
| FTY-011 | merged | infra | [Docker Compose dev stack](FTY-011-docker-compose-dev-stack.md) | Postgres, Redis, API, and worker containers start locally over HTTP. |
| FTY-012 | merged | backend-core | [Backend app skeleton](FTY-012-backend-app-skeleton.md) | FastAPI health endpoint, config, logging, test harness, and typed settings exist (uv toolchain). |
| FTY-013 | merged | mobile-core | [Mobile app skeleton](FTY-013-mobile-app-skeleton.md) | Expo iOS-first app opens to a Today shell with local mock state. |

## Milestone 2: Accounts And Profile

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-020 | merged | contracts | [Auth and user model contracts](FTY-020-auth-user-model-contracts.md) | User/auth identity/profile contracts, migrations, and a local auth path exist. |
| FTY-021 | merged | mobile-core | [Minimal required profile](FTY-021-minimal-required-profile.md) | Height, weight, age/birth year, formula preference, units, timezone are captured. |
| FTY-022 | merged | estimator | [Target calculator contract](FTY-022-target-calculator-contract.md) | Initial RMR/TDEE/goal target calculator has deterministic tests and documented assumptions. |

## Milestone 3: Logging Spine

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-030 | merged | backend-core | [Log event API](FTY-030-log-event-api.md) | User can create a pending raw log event through the API. |
| FTY-031 | merged | mobile-core | [Today timeline UI](FTY-031-today-timeline-ui.md) | Mobile app shows pending and completed events in a Today timeline. |
| FTY-032 | merged | mobile-core | [Polling updates](FTY-032-polling-updates.md) | Mobile app refreshes pending entries until complete. |

## Milestone 4: Estimator Foundation

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-040 | merged | contracts | [Estimator job contract](FTY-040-estimator-job-contract.md) | Job payloads, statuses, retries, and estimation run records are documented and tested. |
| FTY-041 | merged | estimator | [LLM provider config](FTY-041-llm-provider-config.md) | Pi-inspired provider config supports OpenAI, Anthropic, and OpenAI-compatible endpoints. |
| FTY-042 | merged | estimator | [Structured parse step](FTY-042-structured-parse-step.md) | Natural language input parses into food/exercise candidates with schema validation. |
| FTY-043 | merged | estimator | [MET exercise calculator](FTY-043-met-exercise-calculator.md) | Exercise candidates calculate active calories with MET math and tests. |
| FTY-044 | merged | estimator | [Generic food calculator](FTY-044-generic-food-calculator.md) | Simple food entries resolve via USDA data and deterministic serving math. |
| FTY-045 | merged | contracts | [Evidence retrieval contract](FTY-045-evidence-retrieval-contract.md) | Source-backed estimation contracts (providers, evidence records, lookup statuses, fallback) are documented. |

## Milestone 5: Editing And Learning

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-051 | merged | backend-core | [Corrections audit and edit endpoint](FTY-051-corrections-audit.md) | A field edit preserves the original estimate, updates the current value, and appends an immutable correction; editing servings rescales calories/macros. |
| FTY-050 | merged | mobile-core | [Editable food/exercise items](FTY-050-editable-items.md) | User can correct calories, macros, servings, and exercise burn from the Today timeline via FTY-051's endpoint. |
| FTY-052 | merged | backend-core | [Saved foods and aliases (backend)](FTY-052-saved-foods-aliases.md) | A corrected food can be explicitly saved with an alias and reused via a per-user normalized prefix typeahead search endpoint. |
| FTY-053 | merged | mobile-core | [Saved-food save action + typeahead suggestion bar](FTY-053-saved-food-typeahead.md) | "Save this food" persists a corrected food via FTY-052; typing surfaces prefix-matching saved foods in a suggestion bar, and tapping one applies it and skips the estimator. |

## Milestone 6: Evidence Inputs

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
Backend evidence slices (060/061/062) depend only on FTY-045 and are independent of each other, so they author in parallel. Mobile capture is split out: FTY-063 introduces the camera scaffold; FTY-064 builds on it.

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-060 | merged | estimator | [Barcode lookup (backend)](FTY-060-barcode-lookup.md) | A barcode resolves via Open Food Facts through a hardened client and stores source evidence. |
| FTY-076 | merged | contracts | [LLM provider v2 — image input](FTY-076-llm-provider-vision-v2.md) | structured_completion gains an optional image argument (vision model required when used); text-only path unchanged. Prerequisite for FTY-061. |
| FTY-077 | merged | security-privacy | [log_attachments + retention](FTY-077-log-attachments-retention.md) | A log_attachments table holds an uploaded image only on explicit save; discard-by-default retention; additive reversible migration. Prerequisite for FTY-061. |
| FTY-061 | merged | estimator | [Nutrition label extraction pipeline (backend)](FTY-061-nutrition-label-extraction.md) | A label image yields schema-validated nutrition facts via the v2 vision provider; deterministic calories/macros; image discarded unless saved. Depends on FTY-076 + FTY-077. |
| FTY-078 | merged | security-privacy | [Hardened fetcher + SSRF egress policy](FTY-078-hardened-fetcher-ssrf.md) | A hardened fetcher retrieves allowlisted public official-source pages and returns inert text; the full adversarial SSRF suite fails closed. Extends FTY-044's hardened_fetch. Prerequisite for FTY-062. |
| FTY-079 | merged | contracts | [Search-provider adapter](FTY-079-search-provider-adapter.md) | A pluggable search adapter (Brave default, disabled by default for self-host) returns candidate URLs + availability status from a sanitized query; no personal context egresses. Prerequisite for FTY-062. |
| FTY-062 | merged | estimator | [Official-source resolution pipeline step](FTY-062-official-source-search.md) | The estimator runs FTY-079 search + FTY-078 fetch as last resort before model-prior, validates facts, and writes derived_food_items + evidence_sources (no raw pages); disabled provider falls through to model-prior-with-status. Depends on FTY-078 + FTY-079. |
| FTY-063 | merged | mobile-core | [Mobile barcode scanner](FTY-063-mobile-barcode-scanner.md) | Scanning a barcode creates a log event resolved by FTY-060; introduces the reusable camera scaffold. |
| FTY-064 | merged | mobile-core | [Mobile label capture](FTY-064-mobile-label-capture.md) | Capturing a label photo uploads it for FTY-061 extraction; opt-in save of the attachment. |

## Milestone 7: V1 Polish

The two mobile-core items are split backend/mobile for parallel work: weight (070 backend + 074 mobile), daily summary (071 backend + 075 mobile).

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-070 | merged | backend-core | [Weight log backend](FTY-070-weight-log-backend.md) | A weight_entries time series with create/list endpoints and canonical-kg storage exists. |
| FTY-074 | merged | mobile-core | [Mobile weight trend](FTY-074-mobile-weight-trend.md) | User can log weight and view a simple trend chart backed by FTY-070. |
| FTY-071 | merged | backend-core | [Daily totals endpoint](FTY-071-daily-totals-endpoint.md) | A read-only daily-summary endpoint returns calories, macros, target, and exercise burn separately. |
| FTY-075 | merged | mobile-core | [Mobile daily summary](FTY-075-mobile-daily-summary.md) | Today shows calories, macros, target, and exercise burn separately, refreshing as entries complete. |
| FTY-072 | merged | infra | [Self-host setup](FTY-072-self-host-setup.md) | README and Docker Compose support a fresh self-host install with documented FATTY_* env config. |
| FTY-073 | merged | security-privacy | [Security pass](FTY-073-security-pass.md) | Threat model/retention/secrets reviewed; an adversarial test suite proves the boundaries; findings filed as follow-up stories. |

## Release Audit Fixes (Runbook Phase 2)

Findings from the v1 full-system audit (runbook Phase 1, run 2026-06-27). Each is
a scoped fix-story; they author in parallel (no file overlap) and must merge
before FTY-080 is promoted. Other audit findings were accepted as-is (token
revocation + field encryption are documented threat-model deferrals; mobile
API-client boilerplate dedup is a post-v1 follow-up).

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-081 | merged | security-privacy | [Block RFC 6598 CGNAT in SSRF check](FTY-081-ssrf-cgnat-block.md) | `_is_public_address` requires `is_global`; CGNAT `100.64.0.0/10` blocked fail-closed; the `xfail` CGNAT test passes; no SSRF-suite regression. |
| FTY-082 | merged | estimator | [Deduplicate estimator evidence helpers](FTY-082-estimator-shared-helpers.md) | One shared `_content_hash` and one `_record_source_ref`; fingerprint values unchanged (pinned test); existing evidence suites green. |
| FTY-083 | merged | estimator | [Consumed-quantity clarification on labels](FTY-083-label-quantity-clarification.md) | Unresolvable consumed quantity asks for the consumed amount, not the printed serving size; serving-size branch unaffected. |
| FTY-084 | merged | governance | [Release docs polish](FTY-084-release-docs-polish.md) | `/healthz` documented; full evidence source list in the overview; port/retention/OFF/threat-model doc gaps closed; no version/CHANGELOG change. |
| FTY-085 | merged | backend-core | [Alembic psycopg v3 driver (first-boot fix)](FTY-085-alembic-psycopg-driver.md) | A clean `docker compose up` with the default `.env.example` (bare `postgresql://`) runs migrations to completion; alembic normalizes the driver like `app/db.py`; resolver regression test added. **Blocks the v1 tag.** |

> **FTY-085 — release blocker found in the v1 manual test (2026-06-28).** `docker
> compose up` from a clean checkout fails the `migrate` service with
> `ModuleNotFoundError: No module named 'psycopg2'`: `alembic/env.py` uses the raw
> `postgresql://` DSN, so SQLAlchemy picks psycopg2 (not installed) instead of the
> shipped psycopg v3. `app/db.py` already normalizes this for the app runtime; the
> migration path doesn't. The automated gate missed it (tests use SQLite; the
> Phase 3 migration check used an explicit `+psycopg` scheme). **Hold the v1 tag
> until FTY-085 merges**; FTY-080 (release prep) already merged but the tag was not
> cut.

> **FTY-084 / PR #49 — resolved (merged as #49 / commit `84ad596`).** The author's
> first rewrite of the Source Hierarchy in `system-overview.md` ranked
> `official_source` rank-4 instead of the canonical rank-2; the reviewer recorded
> it as COMMENTED rather than CHANGES_REQUESTED, which wedged the loop (steward
> couldn't route a fix from a COMMENTED verdict while `reviewer-approved` stayed
> failure). A targeted `fix-pr` corrected the ranking to rank-2; on re-review the
> reviewer escalated to CHANGES_REQUESTED for a newly-exposed stale cross-reference
> in `evidence-retrieval.md` (cited "ranks 4–5" → "ranks 6–7"), the steward then
> auto-routed the fix, and it merged cleanly. The COMMENTED-verdict wedge is a
> systemic gap in the reviewer/steward loop worth fixing later.

## Milestone 8: Self-Host LLM Provider Access (v1)

**Pulled into v1 (2026-06-28, user decision):** self-hosters must be able to run
estimation without paying per token. Planned via `plan-stories`; the
OAuth/subscription-bridge route was **rejected** (per Pi's docs it's ToS-gray,
detectable, and billed per token, not plan-covered). Resolved design: wrap the
**local first-party Claude Code** (subscription, plan-covered, ToS-clean, tools
disabled) + a truly-free **local-model** path. These are `ready`; the steward
builds them, and the v1 tag now gates on all three merging. FTY-086 is the
superseded umbrella (history only).

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-087 | merged | estimator | [`claude_code` subscription provider](FTY-087-claude-code-subscription-provider.md) | Wrap local Claude Code headless (`claude -p --output-format json --json-schema`), **tools fully disabled**, subscription auth via the local `claude login` session, no API key; schema-validated output; BYO-key providers unchanged. (+security-privacy) |
| FTY-088 | merged | infra | [Claude Code self-host setup](FTY-088-claude-code-selfhost-setup.md) | Claude Code installed in the backend image + one-time `claude login` (persistent session volume) + `FATTY_LLM_PROVIDER=claude_code` docs + `/healthz/sources` availability; no credentials baked/committed. Depends on FTY-087. (+docs) |
| FTY-089 | merged | estimator | [Keyless local-model (Ollama) path](FTY-089-local-model-openai-compatible-keyless.md) | `openai_compatible` validates+runs without an API key (base URL + model still required; no empty Bearer header); Ollama/LM Studio/vLLM documented; keyed providers unchanged. Independent. |
| FTY-086 | candidate | estimator | [Provider login (umbrella — superseded)](FTY-086-provider-login-subscription-auth.md) | Superseded by FTY-087/088/089; kept for history. Do not implement directly. |

## Milestone 9: Release

Phase 4 of `docs/release-runbook.md`. The v1 tag now depends on the release-audit
fixes (FTY-081/082/083/084, merged), the migrate-driver fix (FTY-085, merged), and
the **Milestone 8 provider-access stories (FTY-087/088/089)** merging — plus the
full-system audit + fix loop (runbook Phases 1–3) staying clean. FTY-080 (release
prep) already merged; note its CHANGELOG/README will need a follow-up touch to
cover the provider-access features (FTY-088 includes the docs/CHANGELOG update).
**The v1 tag now ALSO gates on Milestone 10 — the UX redesign tranche
(FTY-090–107)** — per a user decision (2026-06-28): v1 ships already designed, not
as scaffolding. The tag/release/deploy itself is a human step.

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-080 | merged | governance | [v1 release prep](FTY-080-v1-release-prep.md) | v1.0.0 version is consistent, CHANGELOG + README match the shipped product, and full `make verify` is green. Gated on the release runbook + FTY-062/064/070/073/074/075 + FTY-081/082/083/084. (CHANGELOG/README provider-access update lands via FTY-088.) |

## Milestone 10: V1 UX Redesign (gates the v1 tag)

The whole-product UX design (resolved 2026-06-28 via the `design` skill; canonical
doc `fatty/docs/design/ux-design.md`, merged in PR #56) decomposed into an
18-story single-boundary tranche. The functional v1 backend is already built; this
is the deliberate UX/visual layer on top of it (the screens were scaffolding, never
designed). **Build order is a DAG:** the backend/contract foundations + the mobile
design system root the per-screen mobile rebuilds. Most are `ready_with_notes`,
gated on their foundations merging. Three living philosophy principles seeded this
session (Native skeleton/bespoke soul; Encourage the trend not the scale;
Evidence-backed by default) are auto-enforced.

**Foundations (backend / contract + the mobile design system):**

| ID | State | Lane | Story | Notes |
| --- | --- | --- | --- | --- |
| FTY-092 | merged | backend-core | [Item provenance + portion adjust](FTY-092-item-provenance-portion-adjust.md) | Per-item source/`is_edited` in the read-model; amount edit recomputes provenance-preserving (not user-edited). Roots the correction sheet. |
| FTY-093 | merged | estimator | [Item re-match](FTY-093-item-rematch-alternative-sources.md) | List alternative sources + re-resolve to a chosen one (honest provenance). Dep FTY-092. |
| FTY-094 | merged | estimator | [Macro targets](FTY-094-macro-targets.md) | Derive P/C/F targets (evidence-based defaults) in the calculator. |
| FTY-095 | merged | backend-core | [Target manual override](FTY-095-target-manual-override.md) | Calorie/macro override + reset + provenance on `daily_targets`. Dep FTY-094 (serialize the migration). |
| FTY-105 | merged | backend-core | [Macro targets in daily-summary](FTY-105-macro-targets-daily-summary.md) | Surface macro targets + provenance through the read-model. Dep FTY-094 + FTY-095. |
| FTY-096 | merged | backend-core | [Offline submit + pending-unparsed](FTY-096-offline-submit-pending-unparsed.md) | Client idempotency-key dedup on log-event create. |
| FTY-106 | ready_with_notes | backend-core | [Goals + target-reveal endpoint](FTY-106-goals-target-reveal-endpoint.md) | New HTTP route: goal from direction+pace → computed target + provenance (FTY-022 had no route). |
| FTY-097 | merged | mobile-core | [Mobile design system](FTY-097-mobile-design-system.md) | Tokens, light/dark charcoal, display+SF type, materials, motion/haptics, 3-tab shell. Every screen depends on this. |

**Mobile screen rebuilds (depend on FTY-097 + their backend foundations):**

| ID | State | Lane | Story | Notes |
| --- | --- | --- | --- | --- |
| FTY-098 | merged | mobile-core | [Today redesign](FTY-098-today-screen-redesign.md) | Hero/over-budget, macro chips, clustered provenance timeline. Dep FTY-097 + FTY-092 (+ FTY-105 for macro-chip targets). |
| FTY-099 | merged | mobile-core | [Log page redesign](FTY-099-log-page-redesign.md) | Keyboard-up composer, typeahead, capture affordances, in-place skeleton. Dep FTY-097. |
| FTY-100 | merged | mobile-core | [Correction sheet](FTY-100-correction-sheet.md) | Portion + change-match + override + clarify + evidence. Dep FTY-097 + FTY-092 + FTY-093. |
| FTY-101 | ready | mobile-core | [Trends + weigh-ins](FTY-101-trends-redesign-weighin-reminders.md) | Smoothed weight trend + adherence; weekly due-only reminder. Dep FTY-097. |
| FTY-102 | ready | mobile-core | [Profile / Settings](FTY-102-profile-settings-redesign.md) | Control panel; target/macro provenance + override. Dep FTY-097 + FTY-094 + FTY-095 (+ FTY-105). |
| FTY-103 | ready_with_notes | mobile-core | [Onboarding redesign](FTY-103-onboarding-redesign.md) | Goal-led 3-step + target reveal. Dep FTY-097 + FTY-091 + FTY-106. |
| FTY-104 | ready | mobile-core | [Offline-queue logging](FTY-104-offline-queue-logging-mobile.md) | Local outbox + connection banner + reconnect sync. Dep FTY-096 + FTY-097 + FTY-099. |

**Self-host sign-in & connection (mobile):**

| ID | State | Lane | Story | Notes |
| --- | --- | --- | --- | --- |
| FTY-090 | ready | mobile-core | [Session token store](FTY-090-mobile-session-token-store.md) | Persist/hydrate/clear `{serverUrl, token, userId}`; replaces the dogfood shim. |
| FTY-107 | ready_with_notes | mobile-core | [Connect to your server](FTY-107-mobile-connect-to-server.md) | Server-URL entry + QR (URL only) + reachability probe. Dep FTY-097. |
| FTY-091 | ready_with_notes | mobile-core | [Sign-in / create-account](FTY-091-mobile-signin-create-account.md) | Self-host-first auth + signed-out gating. Dep FTY-090 + FTY-107 + FTY-097. |

**Open reconciliation notes (non-blocking, resolve when the stories are touched):**

- **FTY-098 / FTY-102 also consume FTY-105** (macro-chip / macro-target display) — their story files list FTY-094/095 but should treat FTY-105 (read-model surfacing) as the merge-before dep.
- **Contract ownership:** FTY-094 (derive) vs FTY-095 (persist columns) and FTY-095 vs FTY-105 (the `daily-summary.md` version bump) — confirm single ownership before both author, to avoid a double contract-doc edit.
- **FTY-097 owns the 3-tab shell** — FTY-099 wrote it as a separate nav story; it isn't, 097 covers it.
- **Activity-level gap:** the design's Profile BODY assumes an activity level, but the backend has no activity field (calculator uses fixed 1.2 sedentary). FTY-102 deferred it; needs a small backend story or a design trim to support it.

## Parallel Quick-Wins (non-mobile lanes — 2026-06-28)

While Milestone 10's mobile-core queue (FTY-090/091/100–104/107) is in flight, a
cross-lane audit (2026-06-28) surfaced small, high-value hardening/robustness
fixes in the **idle** lanes so the steward can run them in parallel with the
mobile work. All independent (`approved_dependencies: []`), each one focused
single-boundary PR. Theme: **fail-closed** — plausible-but-bad input should
return a clean 4xx / non-match, never an unhandled 500 or a crashed worker.

Lane note: lanes serialize by changed-file path. FTY-108 (governance), FTY-109
(infra) and FTY-110 (estimator) each occupy a distinct free lane and run fully
parallel to mobile and each other. FTY-111 and FTY-112 are both backend-core
(the security-headers change lives in `backend/app/main.py`, which is
backend-core, not a non-serializing security-privacy *code* lane), so they
serialize back-to-back rather than simultaneously.

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-108 | merged | governance | [Expand Dependabot to app deps](FTY-108-dependabot-app-dependencies.md) | Dependabot covers the backend `uv`/pip, mobile `npm`, and Docker base-image ecosystems (not just github-actions); config-only, no dep bumps in the PR. |
| FTY-109 | merged | infra | [Compose network / ops hardening](FTY-109-compose-network-hardening.md) | Postgres/Redis host ports no longer published (unauth Redis off the LAN); worker gains a healthcheck; long-lived services get a restart policy. Redis auth is a noted follow-up. |
| FTY-110 | ready_with_notes | estimator | [Evidence clients fail closed](FTY-110-evidence-client-fail-closed.md) | A malformed FDC/OFF payload maps to a clean non-retryable ResponseError → non-match/clarify (not a worker-crashing `ValidationError`); over-long fields truncate; `FdcClient.lookup`/`list_matches` dedup so both inherit the guard. |
| FTY-111 | ready | backend-core | [Fail closed at profile + registration boundary](FTY-111-backend-input-boundary-fail-closed.md) | Explicit-null on a non-nullable profile field → 422 (was 500); the register check-then-insert race returns 409 on the unique-index loser (was 500). No migration, no contract change. |
| FTY-112 | ready_with_notes | backend-core | [Baseline security headers + prod docs gating](FTY-112-security-headers-prod-docs.md) | Responses carry nosniff / frame / referrer headers; interactive `/docs`/`/redoc`/`/openapi.json` disabled when `environment == production`. Serializes on backend-core after FTY-111. |

**Second wave (queued 2026-06-28 — depth in the two lanes with the most audit findings).**
These serialize *within* their lane (estimator runs them after FTY-110; backend-core
after FTY-111/112), but the whole batch runs in parallel with the mobile-core queue.

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-113 | ready_with_notes | estimator | [LLM rate-limit retry + backoff](FTY-113-llm-rate-limit-retry-backoff.md) | 429/408/425 reclassify as transient and retry with jittered backoff (injectable sleep); persistent rate-limit still fails closed; non-retryable 4xx unchanged. |
| FTY-114 | ready_with_notes | estimator | [LLM provider output hardening](FTY-114-llm-provider-output-hardening.md) | Transport response read is size-capped (parity with `hardened_fetch`); Claude Code stdout tolerates a prose line / ```json fences but rejects trailing junk. |
| FTY-115 | ready_with_notes | estimator | [Nutrition plausibility bound](FTY-115-nutrition-plausibility-bound.md) | Impossible per-100g facts (energy > ~900 kcal, negative macros — the OFF kJ-as-kcal case) fall through to non-match/clarify, not a stored absurd total. Coordinates with FTY-110 (same FDC/OFF mapping). |
| FTY-116 | ready | backend-core | [Non-root backend container](FTY-116-non-root-backend-container.md) | `backend/Dockerfile` runs api/worker/migrate as a non-root user (chowned app + venv); build + compose-up stay healthy. |
| FTY-117 | ready | backend-core | [`/readyz` DB readiness probe](FTY-117-readyz-db-readiness-probe.md) | New `/readyz` runs `SELECT 1` → 200 ready / 503 when the DB is down (no 500, no detail leak); `/healthz` liveness unchanged; queue check deferred. |
| FTY-118 | ready_with_notes | backend-core | [Auth endpoint rate-limit](FTY-118-auth-endpoint-rate-limit.md) | `/login` + `/register` per-IP (and per-account) Redis-backed throttle → 429 + Retry-After; tuned not to break the mobile retry/reconnect path. |

**Still-unqueued runners-up (lowest urgency):** bound weight-entry `effective_date` against typos
(backend-core, S); the timezone-window / active-target / `FdcClient` pure-refactor dedups
(backend-core + estimator, S each — drift-reduction, no behaviour change). The known
**activity-level gap** (calculator fixed at 1.2 sedentary vs the Profile design) is confirmed
real but M+ (estimator + profile schema + migration) — leave as already-planned, not a quick win.

## Story Promotion Rule

Only promote a story to `ready` or `ready_with_notes` when it has:

- scope,
- lane,
- dependencies,
- non-goals,
- affected contracts or an explicit "none",
- security/privacy note,
- acceptance criteria,
- verification plan,
- YAML metadata with approved dependencies for `ready` and `ready_with_notes`,
- readiness sanity pass.

Use `ready_with_notes` when the story is safe for autonomous implementation but contains non-blocking planning notes. Keep stories as `candidate` when missing decisions would make the work unsafe, impossible to verify, or likely to conflict with unmet dependencies.

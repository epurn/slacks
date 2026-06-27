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
| FTY-053 | ready_with_notes | mobile-core | [Saved-food save action + typeahead suggestion bar](FTY-053-saved-food-typeahead.md) | "Save this food" persists a corrected food via FTY-052; typing surfaces prefix-matching saved foods in a suggestion bar, and tapping one applies it and skips the estimator. |

## Milestone 6: Evidence Inputs

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
Backend evidence slices (060/061/062) depend only on FTY-045 and are independent of each other, so they author in parallel. Mobile capture is split out: FTY-063 introduces the camera scaffold; FTY-064 builds on it.

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-060 | merged | estimator | [Barcode lookup (backend)](FTY-060-barcode-lookup.md) | A barcode resolves via Open Food Facts through a hardened client and stores source evidence. |
| FTY-076 | ready | contracts | [LLM provider v2 — image input](FTY-076-llm-provider-vision-v2.md) | structured_completion gains an optional image argument (vision model required when used); text-only path unchanged. Prerequisite for FTY-061. |
| FTY-077 | ready | security-privacy | [log_attachments + retention](FTY-077-log-attachments-retention.md) | A log_attachments table holds an uploaded image only on explicit save; discard-by-default retention; additive reversible migration. Prerequisite for FTY-061. |
| FTY-061 | ready | estimator | [Nutrition label extraction pipeline (backend)](FTY-061-nutrition-label-extraction.md) | A label image yields schema-validated nutrition facts via the v2 vision provider; deterministic calories/macros; image discarded unless saved. Depends on FTY-076 + FTY-077. |
| FTY-062 | ready_with_notes | security-privacy | [Official source search (backend)](FTY-062-official-source-search.md) | Sanitized search + a hardened SSRF-safe fetcher retrieve official nutrition evidence for unresolved named products. |
| FTY-063 | ready | mobile-core | [Mobile barcode scanner](FTY-063-mobile-barcode-scanner.md) | Scanning a barcode creates a log event resolved by FTY-060; introduces the reusable camera scaffold. |
| FTY-064 | ready | mobile-core | [Mobile label capture](FTY-064-mobile-label-capture.md) | Capturing a label photo uploads it for FTY-061 extraction; opt-in save of the attachment. |

## Milestone 7: V1 Polish

The two mobile-core items are split backend/mobile for parallel work: weight (070 backend + 074 mobile), daily summary (071 backend + 075 mobile).

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-070 | ready | backend-core | [Weight log backend](FTY-070-weight-log-backend.md) | A weight_entries time series with create/list endpoints and canonical-kg storage exists. |
| FTY-074 | ready | mobile-core | [Mobile weight trend](FTY-074-mobile-weight-trend.md) | User can log weight and view a simple trend chart backed by FTY-070. |
| FTY-071 | ready | backend-core | [Daily totals endpoint](FTY-071-daily-totals-endpoint.md) | A read-only daily-summary endpoint returns calories, macros, target, and exercise burn separately. |
| FTY-075 | ready | mobile-core | [Mobile daily summary](FTY-075-mobile-daily-summary.md) | Today shows calories, macros, target, and exercise burn separately, refreshing as entries complete. |
| FTY-072 | ready_with_notes | infra | [Self-host setup](FTY-072-self-host-setup.md) | README and Docker Compose support a fresh self-host install with documented FATTY_* env config. |
| FTY-073 | ready_with_notes | security-privacy | [Security pass](FTY-073-security-pass.md) | Threat model/retention/secrets reviewed; an adversarial test suite proves the boundaries; findings filed as follow-up stories. |

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

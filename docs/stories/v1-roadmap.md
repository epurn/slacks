# V1 Roadmap

This is the initial story order for Fatty v1. Keep stories small enough for one focused PR.

## Milestone 0: Repository Governance

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-000 | merged | governance | Governance, CI, branch protection, reviewer gate | Main is protected; governance and separate reviewer checks are required. |

## Milestone 1: Project Skeleton

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-010 | ready_with_notes | contracts | [Monorepo scaffold](FTY-010-monorepo-scaffold.md) | Backend, mobile, shared docs, and root verification commands exist. |
| FTY-011 | ready_with_notes | infra | [Docker Compose dev stack](FTY-011-docker-compose-dev-stack.md) | Postgres, Redis, API, and worker services are represented in a local Compose stack. |
| FTY-012 | ready_with_notes | backend-core | [Backend app skeleton](FTY-012-backend-app-skeleton.md) | FastAPI health endpoint, config, logging, and test harness exist. |
| FTY-013 | ready_with_notes | mobile-core | [Mobile app skeleton](FTY-013-mobile-app-skeleton.md) | Expo iOS-first app opens to a Today shell with local mock state. |

## Milestone 2: Accounts And Profile

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-020 | candidate | contracts | Auth and user model contracts | User, auth identity, profile, goal, and target contracts are documented. |
| FTY-021 | candidate | backend-core | Local auth and profile API | Self-host-friendly auth and profile endpoints persist user profile data. |
| FTY-022 | candidate | mobile-core | Minimal required profile setup | Height, weight, age/birth year, formula setting, units, timezone, and goal inputs are captured. |
| FTY-023 | candidate | estimator | Target calculator | Initial RMR, TDEE, calorie target, and macro target calculations have deterministic tests. |

## Milestone 3: Logging Spine

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-030 | candidate | contracts | Log event contract | Raw log event, attachment, derived item, and status contracts are documented. |
| FTY-031 | candidate | backend-core | Log event API | User can create pending food/exercise log events through the API. |
| FTY-032 | candidate | mobile-core | Today timeline UI | Mobile app shows pending, needs-info, failed, edited, and completed timeline entries. |
| FTY-033 | candidate | mobile-core | Polling updates | Mobile app polls pending entries until estimation completes or needs clarification. |

## Milestone 4: Evidence Retrieval

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-040 | ready_with_notes | contracts | [Evidence retrieval contract](FTY-040-evidence-retrieval-contract.md) | Source-backed lookup rules, provider boundaries, evidence records, and fallback statuses are documented. |
| FTY-041 | candidate | backend-core | Provider configuration | Server-side config supports LLM, USDA, Open Food Facts, and search providers without exposing secrets to clients. |
| FTY-042 | candidate | estimator | USDA FoodData Central adapter | Generic food lookup returns normalized nutrients and source evidence. |
| FTY-043 | candidate | estimator | Open Food Facts adapter | Barcode and packaged-product lookup returns normalized nutrients and source evidence. |
| FTY-044 | candidate | security-privacy | Search and hardened fetcher | Official-source search and fetch enforce SSRF, redirect, content, timeout, and storage limits. |

## Milestone 5: Estimator Foundation

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-050 | candidate | contracts | Estimator job contract | Job payloads, statuses, retries, estimation runs, and clarification records are documented. |
| FTY-051 | candidate | backend-core | Estimation queue worker | Pending log events enqueue idempotent async jobs and store estimation run status. |
| FTY-052 | candidate | estimator | Structured parse step | Natural language input parses into food/exercise candidates with schema validation. |
| FTY-053 | candidate | estimator | Generic food calculator | Source-backed generic food entries calculate calories and macros with deterministic serving math. |
| FTY-054 | candidate | estimator | MET exercise calculator | Exercise candidates calculate active calories with MET math and deterministic tests. |
| FTY-055 | candidate | estimator | Clarifying questions | Missing portion or activity details can produce a follow-up question instead of a low-quality estimate. |

## Milestone 6: Named Products, Labels, And Official Sources

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-060 | candidate | mobile-core | Barcode scan flow | Mobile app can scan a barcode and create a source-backed pending log event. |
| FTY-061 | candidate | estimator | Official restaurant and manufacturer lookup | Named restaurant/manufacturer items use search and hardened fetch before model-prior fallback. |
| FTY-062 | candidate | estimator | Nutrition label image extraction | Label photo creates structured nutrition facts with validation and source status. |
| FTY-063 | candidate | mobile-core | Evidence and source display | Timeline items show source/status icons and editable assumptions without clutter. |

## Milestone 7: Editing And Learning

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-070 | candidate | mobile-core | Editable food and exercise items | User can correct calories, macros, servings, and exercise burn. |
| FTY-071 | candidate | backend-core | Corrections audit | Edits create correction records instead of silently overwriting estimates. |
| FTY-072 | candidate | backend-core | Saved foods and aliases | Corrected recurring foods can be saved and reused. |
| FTY-073 | candidate | mobile-core | Explicit remember-this flow | User can approve saved foods, aliases, and portion preferences instead of silent auto-learning. |

## Milestone 8: Summaries, Self-Host, And Release

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-080 | candidate | mobile-core | Daily summaries | Today totals show calories, macros, target, and exercise burn separately. |
| FTY-081 | candidate | mobile-core | Weight trend logging | User can log weight and view a simple trend chart. |
| FTY-082 | candidate | backend-core | Deletion and retention controls | User can delete logs, attachments, saved foods, aliases, memories, profile data, and account data. |
| FTY-083 | candidate | infra | Self-host setup | README and Docker Compose support a fresh self-host install with provider configuration. |
| FTY-084 | candidate | security-privacy | Security and privacy hardening pass | Threat model, retention, adversarial estimator tests, secret handling, and fetch safety are reviewed. |
| FTY-085 | candidate | docs | V1 release docs | Public docs describe setup, provider requirements, safety boundaries, and known limitations. |

## V1 Product Cuts

- iOS-first Expo app; web is secondary if it falls out naturally.
- Self-host-friendly auth first; Sign in with Apple can come later.
- Nutrition label photos and barcode scans are v1; plated food portion photos are not v1.
- Natural language input is a fast entry point, not a chatbot UI.
- Learning is explicit and inspectable; no silent auto-learning.
- Data deletion for logs, profile, attachments, saved foods, aliases, and memories is v1. Full export can follow.
- Evidence retrieval is required when a named product, restaurant item, barcode, nutrition label, or generic food lookup is possible.
- Model-prior estimates are a documented fallback only after source lookup fails or is unavailable.

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

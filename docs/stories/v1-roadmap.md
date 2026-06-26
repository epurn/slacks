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
| FTY-011 | ready_with_notes | infra | [Docker Compose dev stack](FTY-011-docker-compose-dev-stack.md) | Postgres, Redis, API, and worker containers start locally over HTTP. |
| FTY-012 | ready | backend-core | [Backend app skeleton](FTY-012-backend-app-skeleton.md) | FastAPI health endpoint, config, logging, test harness, and typed settings exist (uv toolchain). |
| FTY-013 | ready | mobile-core | [Mobile app skeleton](FTY-013-mobile-app-skeleton.md) | Expo iOS-first app opens to a Today shell with local mock state. |

## Milestone 2: Accounts And Profile

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-020 | ready_with_notes | contracts | [Auth and user model contracts](FTY-020-auth-user-model-contracts.md) | User/auth identity/profile contracts, migrations, and a local auth path exist. |
| FTY-021 | ready | mobile-core | [Minimal required profile](FTY-021-minimal-required-profile.md) | Height, weight, age/birth year, formula preference, units, timezone are captured. |
| FTY-022 | ready_with_notes | estimator | [Target calculator contract](FTY-022-target-calculator-contract.md) | Initial RMR/TDEE/goal target calculator has deterministic tests and documented assumptions. |

## Milestone 3: Logging Spine

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-030 | ready | backend-core | [Log event API](FTY-030-log-event-api.md) | User can create a pending raw log event through the API. |
| FTY-031 | ready | mobile-core | [Today timeline UI](FTY-031-today-timeline-ui.md) | Mobile app shows pending and completed events in a Today timeline. |
| FTY-032 | ready | mobile-core | [Polling updates](FTY-032-polling-updates.md) | Mobile app refreshes pending entries until complete. |

## Milestone 4: Estimator Foundation

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-040 | merged | contracts | [Estimator job contract](FTY-040-estimator-job-contract.md) | Job payloads, statuses, retries, and estimation run records are documented and tested. |
| FTY-041 | merged | estimator | [LLM provider config](FTY-041-llm-provider-config.md) | Pi-inspired provider config supports OpenAI, Anthropic, and OpenAI-compatible endpoints. |
| FTY-042 | merged | estimator | [Structured parse step](FTY-042-structured-parse-step.md) | Natural language input parses into food/exercise candidates with schema validation. |
| FTY-043 | merged | estimator | [MET exercise calculator](FTY-043-met-exercise-calculator.md) | Exercise candidates calculate active calories with MET math and tests. |
| FTY-044 | merged | estimator | [Generic food calculator](FTY-044-generic-food-calculator.md) | Simple food entries resolve via USDA data and deterministic serving math. |

## Milestone 5: Editing And Learning

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-050 | candidate | mobile-core | Editable food/exercise items | User can correct calories, macros, servings, and exercise burn. |
| FTY-051 | candidate | backend-core | Corrections audit | Edits create correction records instead of silently overwriting estimates. |
| FTY-052 | candidate | backend-core | Saved foods and aliases | Corrected recurring foods can be saved and reused. |

## Milestone 6: Evidence Inputs

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-060 | candidate | estimator | Barcode lookup | Barcode input checks Open Food Facts and stores source evidence. |
| FTY-061 | candidate | estimator | Nutrition label image extraction | Label photo creates structured nutrition facts with source status. |
| FTY-062 | candidate | security-privacy | Official source search | Sanitized Brave search and hardened fetcher retrieve official nutrition evidence. |

## Milestone 7: V1 Polish

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-070 | candidate | mobile-core | Weight trend logging | User can log weight and view a simple trend chart. |
| FTY-071 | candidate | mobile-core | Daily summaries | Today totals show calories, macros, target, and exercise burn separately. |
| FTY-072 | candidate | infra | Self-host setup | README and Docker Compose support a fresh self-host install. |
| FTY-073 | candidate | security-privacy | Security pass | Threat model, retention, adversarial estimator tests, and secret handling are reviewed. |

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

# V1 Roadmap

This is the initial story order for Fatty v1. Keep stories small enough for one focused PR.

## Milestone 0: Operating System

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-000 | merged | governance | Governance, CI, branch protection, reviewer gate | Main is protected; governance and separate reviewer checks are required. |
| FTY-001 | merged | governance | [Author-agent loop and PR rejection monitor](FTY-001-author-agent-loop.md) | Story slicing docs exist; recurring monitor is configured. |

## Milestone 1: Project Skeleton

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-010 | ready_with_notes | contracts | [Monorepo scaffold](FTY-010-monorepo-scaffold.md) | Backend, mobile, shared docs, and root verification commands exist. |
| FTY-011 | candidate | infra | Docker Compose dev stack | Postgres, Redis, API, and worker containers start locally. |
| FTY-012 | candidate | backend-core | Backend app skeleton | FastAPI health endpoint, config, logging, test harness, and typed settings exist. |
| FTY-013 | candidate | mobile-core | Mobile app skeleton | Expo iOS-first app opens to a Today shell with local mock state. |

## Milestone 2: Accounts And Profile

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-020 | candidate | contracts | Auth and user model contracts | User/auth identity/profile contracts and migrations exist. |
| FTY-021 | candidate | mobile-core | Minimal required profile | Height, weight, age/birth year, formula setting, units, timezone are captured. |
| FTY-022 | candidate | estimator | Target calculator contract | Initial RMR/TDEE/goal target calculator has deterministic tests and documented assumptions. |

## Milestone 3: Logging Spine

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-030 | candidate | backend-core | Log event API | User can create a pending raw log event through the API. |
| FTY-031 | candidate | mobile-core | Today timeline UI | Mobile app shows pending and completed events in a Today timeline. |
| FTY-032 | candidate | mobile-core | Polling updates | Mobile app refreshes pending entries until complete. |

## Milestone 4: Estimator Foundation

| ID | State | Lane | Story | Acceptance |
| --- | --- | --- | --- | --- |
| FTY-040 | candidate | contracts | Estimator job contract | Job payloads, statuses, retries, and estimation run records are documented and tested. |
| FTY-041 | candidate | estimator | LLM provider config | Pi-inspired provider config supports OpenAI, Anthropic, and OpenAI-compatible endpoints. |
| FTY-042 | candidate | estimator | Structured parse step | Natural language input parses into food/exercise candidates with schema validation. |
| FTY-043 | candidate | estimator | MET exercise calculator | Exercise candidates calculate active calories with MET math and tests. |
| FTY-044 | candidate | estimator | Generic food calculator | Simple food entries resolve via USDA data and deterministic serving math. |

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
- verification plan.

Use `ready_with_notes` when the story is safe for autonomous implementation but contains non-blocking planning notes. Keep stories as `candidate` when missing decisions would make the work unsafe, impossible to verify, or likely to conflict with unmet dependencies.

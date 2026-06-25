# V1 Roadmap

This is the initial story order for Fatty v1. Keep stories small enough for one focused PR.

## Milestone 0: Operating System

| ID | State | Story | Acceptance |
| --- | --- | --- | --- |
| FTY-000 | merged | Governance, CI, branch protection, reviewer gate | Main is protected; governance and separate reviewer checks are required. |
| FTY-001 | ready | Author-agent loop and PR rejection monitor | Story slicing docs exist; recurring monitor is configured. |

## Milestone 1: Project Skeleton

| ID | State | Story | Acceptance |
| --- | --- | --- | --- |
| FTY-010 | ready | Monorepo scaffold | Backend, mobile, shared docs, and root verification commands exist. |
| FTY-011 | candidate | Docker Compose dev stack | Postgres, Redis, API, and worker containers start locally. |
| FTY-012 | candidate | Backend app skeleton | FastAPI health endpoint, config, logging, test harness, and typed settings exist. |
| FTY-013 | candidate | Mobile app skeleton | Expo iOS-first app opens to a Today shell with local mock state. |

## Milestone 2: Accounts And Profile

| ID | State | Story | Acceptance |
| --- | --- | --- | --- |
| FTY-020 | candidate | Auth and user model contracts | User/auth identity/profile contracts and migrations exist. |
| FTY-021 | candidate | Minimal required profile | Height, weight, age/birth year, formula setting, units, timezone are captured. |
| FTY-022 | candidate | Target calculator contract | Initial RMR/TDEE/goal target calculator has deterministic tests and documented assumptions. |

## Milestone 3: Logging Spine

| ID | State | Story | Acceptance |
| --- | --- | --- | --- |
| FTY-030 | candidate | Log event API | User can create a pending raw log event through the API. |
| FTY-031 | candidate | Today timeline UI | Mobile app shows pending and completed events in a Today timeline. |
| FTY-032 | candidate | Polling updates | Mobile app refreshes pending entries until complete. |

## Milestone 4: Estimator Foundation

| ID | State | Story | Acceptance |
| --- | --- | --- | --- |
| FTY-040 | candidate | Estimator job contract | Job payloads, statuses, retries, and estimation run records are documented and tested. |
| FTY-041 | candidate | LLM provider config | Pi-inspired provider config supports OpenAI, Anthropic, and OpenAI-compatible endpoints. |
| FTY-042 | candidate | Structured parse step | Natural language input parses into food/exercise candidates with schema validation. |
| FTY-043 | candidate | MET exercise calculator | Exercise candidates calculate active calories with MET math and tests. |
| FTY-044 | candidate | Generic food calculator | Simple food entries resolve via USDA data and deterministic serving math. |

## Milestone 5: Editing And Learning

| ID | State | Story | Acceptance |
| --- | --- | --- | --- |
| FTY-050 | candidate | Editable food/exercise items | User can correct calories, macros, servings, and exercise burn. |
| FTY-051 | candidate | Corrections audit | Edits create correction records instead of silently overwriting estimates. |
| FTY-052 | candidate | Saved foods and aliases | Corrected recurring foods can be saved and reused. |

## Milestone 6: Evidence Inputs

| ID | State | Story | Acceptance |
| --- | --- | --- | --- |
| FTY-060 | candidate | Barcode lookup | Barcode input checks Open Food Facts and stores source evidence. |
| FTY-061 | candidate | Nutrition label image extraction | Label photo creates structured nutrition facts with source status. |
| FTY-062 | candidate | Official source search | Sanitized Brave search and hardened fetcher retrieve official nutrition evidence. |

## Milestone 7: V1 Polish

| ID | State | Story | Acceptance |
| --- | --- | --- | --- |
| FTY-070 | candidate | Weight trend logging | User can log weight and view a simple trend chart. |
| FTY-071 | candidate | Daily summaries | Today totals show calories, macros, target, and exercise burn separately. |
| FTY-072 | candidate | Self-host setup | README and Docker Compose support a fresh self-host install. |
| FTY-073 | candidate | Security pass | Threat model, retention, adversarial estimator tests, and secret handling are reviewed. |

## Story Promotion Rule

Only promote a story to `ready` when it has:

- scope,
- non-goals,
- affected contracts,
- security/privacy note,
- acceptance criteria,
- verification plan.


# FTY-176 manual verification — failed-parse rows: Retry + Edit-as-text

Story-required manual verification of PR #153, run 2026-07-02 on an
**iPhone 17 Pro simulator (iOS 26.5)** against a **real local backend** —
not the E2E mock. Screenshots below are the before/after evidence required by
the story's verification bar.

## Setup

- Backend: FastAPI API (`uv run python -m app`) + Celery estimation worker
  (`celery -A app.worker:celery_app worker`) + Postgres 16.4 + Redis 7, schema
  at Alembic head. Default `FATTY_LLM_PROVIDER=fake` with no scripted
  responses: the parse step genuinely raises `LLMConfigurationError` →
  `StepFailed("provider_error")` → the event terminates in `failed` through
  the real async pipeline (POST → `pending` → worker → `failed`). No secrets
  involved.
- Mobile: debug binary built via `expo prebuild` + `xcodebuild`, JS served by
  Metro **without** `EXPO_PUBLIC_FATTY_E2E` (E2E launch mode off, real fetch,
  real auth). Fresh account registered through the API; signed in through the
  app's Connect → Sign in screens (`http://localhost:8123`).
- Driven with Maestro 2.6.1; screenshots captured at each evidence point.

## Flow exercised

| # | Screenshot | Evidence |
|---|------------|----------|
| 1 | `01-today-empty.png` | Signed in on Today, empty day, real target (1,643 kcal) from the backend |
| 2 | `02-failed-row-actionable.png` | Submitted gibberish `zxqwvb plarg blorf` → real failed parse renders the calm "Couldn't read that" row with **Retry** and **Edit as text**, trailing `—` (uncounted) |
| 3 | `03-retry-pending-no-duplicate.png` | Tapped Retry → failed row superseded **in place** by a fresh "Waiting" pending attempt; asserted `failed-parse-row` not visible (no stale duplicate) |
| 4 | `04-retry-failed-again-actionable.png` | The retry genuinely failed again → the same actionable failed row returns — no dead end. Pixel-identical to `02` by design: the UI returns to exactly the same actionable state (Maestro asserted the intermediate pending state in step 3) |
| 5 | `05-edit-as-text-prefilled.png` | Tapped Edit as text → composer prefilled with the failed text, submit enabled, failed row superseded |
| 6 | `06-edited-resubmitted-pending.png` | Appended a correction and resubmitted through the same create path → new pending attempt, no stale duplicate |

## Backend event log (independent evidence)

`GET /api/users/{id}/log-events` after the run — three distinct events, all
processed by the real pipeline; the Retry created a **new** event (fresh
idempotency key, no dedup replay):

```
eebce737 | failed | 'zxqwvb plarg blorf'                             | 08:35:35
4f26049b | failed | 'zxqwvb plarg blorf'                             | 08:35:41  (Retry)
dca777fe | failed | 'zxqwvb plarg blorf corrected to grilled chicken' | 08:35:50  (Edit as text)
```

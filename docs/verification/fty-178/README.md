# FTY-178 manual verification — Today hero copy + calm states

Story-required manual verification of PR #160, run 2026-07-02 on an
**iPhone 17 Pro simulator (iOS 26.5)** against a **real local backend** —
not the E2E mock. The six required state screenshots (empty / populated /
summary-load error × light / dark) are below, plus one bonus shot of the
error state with a previously loaded summary.

## Setup

- Backend: FastAPI API (`uv run uvicorn app.main:app`) + Celery estimation
  worker + Postgres 16 + Redis 7 at Alembic head, on dedicated local ports.
  `FATTY_LLM_PROVIDER=claude_code` (real LLM parse) and
  `FATTY_FDC_API_KEY=DEMO_KEY` (real USDA FoodData Central lookups via the
  public demo key). No secrets involved.
- Mobile: debug binary built via `expo prebuild` + `xcodebuild`, JS served by
  Metro **without** `EXPO_PUBLIC_FATTY_E2E` (E2E launch mode off, real fetch,
  real auth). Fresh account registered through the API (derived target
  1,643 kcal); signed in through the app's Connect → Sign in screens.
- Driven with Maestro 2.6.1; light/dark switched via
  `xcrun simctl ui booted appearance`.

## The populated day is real pipeline output

Submitted `one medium banana` through the composer → the real worker parsed
it (claude_code) and stopped at `needs_clarification` ("How much did you
have…") → answered `118 grams` through the app's clarify sheet → the
re-estimation resolved via the real USDA FDC lookup to a 118 g / 408 kcal
item, and the daily summary flipped to `has_intake: true` with 408 consumed.
Every state below is the hero rendering genuine backend responses.

## Screenshot index

| # | Screenshot | State | Evidence |
|---|------------|-------|----------|
| 1 | `01-empty-light.png` | Empty day, light | Hero reads `0 / 1,643 kcal · 1,643 to go` — no `0%`, empty track, single "Log your first thing" invite |
| 2 | `02-empty-dark.png` | Empty day, dark | Same copy, dark palette |
| 3 | `03-populated-light.png` | Populated, light | Hero reads `408 / 1,643 kcal · 25%` with `1,235 to go` context line; resolved entry in timeline |
| 4 | `04-populated-dark.png` | Populated, dark | Same copy, dark palette |
| 5 | `05-error-light.png` | Summary-load error, light | API stopped, app cold-launched: hero shell renders the `Summary unavailable / Try again below` state (never null/blank) with the calm inline error + "Try again" retry; timeline error text in the legible theme token |
| 6 | `06-error-dark.png` | Summary-load error, dark | Same forced-error state, dark palette |
| 7 | `07-error-cached-summary-dark.png` | Bonus: error after a loaded day | API stopped after the summary had loaded, then Refresh: the hero keeps the last-known summary and the calm inline error + retry appears beneath — no coral takeover, no blank hero |

Forced-error method: the backend API process was stopped, then (5/6) the app
was cold-relaunched so the initial summary fetch fails with no cached
summary, and (7) Refresh was tapped on an already-loaded day.

## smoke.yaml on iOS (reviewer question)

The prior head's `smoke.yaml` hero assertions matched the *visual*
status-line text; on iOS the hero container is `accessible={true}` and its
children are hidden from the accessibility tree, so only the collapsed label
is exposed and the flow failed at
`assertVisible: ".*0 / 2,000 kcal · 2,000 to go.*"` (reproduced locally).
The assertions now match the combined accessibility label
(`0 of 2,000 kcal, 2,000 remaining` / `120 of 2,000 kcal, 6 percent, 1,880
remaining`) — the same approach `clarify.yaml` step 11 already uses, which
Android CI matches via `contentDescription`. The updated flow passes
end-to-end on this iOS simulator (all 13 steps green).

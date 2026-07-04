# FTY-188 manual verification — Adherence card honesty

Story-required visual evidence for the Trends adherence card's honest render
states, captured 2026-07-04 on an iOS 26.5 simulator against the **E2E fixture
harness** (`EXPO_PUBLIC_FATTY_E2E` dev build — a synthetic session, every API
call mocked from `mobile/e2e/fixtures.ts`, no live backend, no real account).

The card previously lied twice (UX polish audit D2): it printed
"No intake data for this range." whenever no day carried *counted* intake — even
when entries existed but were **uncounted** (awaiting a detail) — and it left a
muted strip standing in for a resolved state. This story threads FTY-223's
per-day `uncounted_entries` count through `computeAdherence` and renders four
mutually-exclusive states (loading → error / empty / uncounted / data), each with
its own screen-reader label.

## Method

- Leased a dedicated headless simulator via `sim-slot.sh` (Metro on the leased
  port; never `booted`).
- Ran this worktree's Metro in E2E fixture mode and loaded the dev client via
  the `fatty://expo-development-client` deep link, then navigated to the Trends
  tab with the `fatty://trends` route deep link.
- To drive each honest state deterministically, temporarily pointed the E2E
  range fixture `e2eDailySummaryRange` at:
  - an **uncounted-only** range (every day `has_intake: false`,
    `uncounted_entries` summing to 3) → card must say "N entries awaiting
    details", and
  - a **genuinely-empty** range (every day `has_intake: false`,
    `uncounted_entries: 0`) → card must show the honest empty invite.
  The temporary fixture edit was reverted before commit; only the permanent
  `uncounted_entries` field additions remain in `mobile/e2e/fixtures.ts`.
- Captured each state in light and dark (`simctl ui … appearance`).

## Screenshot index

| Screenshot | State | Evidence |
|---|---|---|
| `adherence-uncounted-light.png` | Logged-but-uncounted (light) | Card reads **"3 entries awaiting details"** + "Add their details on Today to count them toward your intake." — **not** "No intake data". No hanging skeleton / muted strip. |
| `adherence-uncounted-dark.png` | Logged-but-uncounted (dark) | Same honest copy renders in dark mode. |
| `adherence-empty-light.png` | Genuinely empty (light) | Card reads **"No meals logged in this range yet."** + "Your logged meals will show up here." — the honest empty invite. |
| `adherence-empty-dark.png` | Genuinely empty (dark) | Same empty invite renders in dark mode. |

The uncounted and empty states are visibly distinct copy (never the shared false
"No intake data" string), and in every frame the read has **resolved** — no
never-filling skeleton remains. The loading→resolves guarantee and the distinct
screen-reader labels for all four states are additionally asserted in
`mobile/components/TrendsScreen.test.tsx` (describe: "adherence honesty
(FTY-188)") and the state classification in `mobile/state/trends.test.ts`
(describe: "adherenceContentState").

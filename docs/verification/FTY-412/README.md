# FTY-412 — Nutrition-label scanning produces a usable result end-to-end

Running-app evidence for the repro-gated reliability fix. Every screenshot below
is a **real captured-photo round trip** on a leased simulator against a **live
backend** running the real `claude_code` vision provider — not fixtures, not the
E2E mock, not a render-level test.

## The located break

Label scanning failed **100% of the time** on a subscription (`claude_code`)
deployment, for two compounding reasons in the provider layer:

1. `ClaudeCodeProvider._complete` raised `LLMConfigurationError` on *any* image
   input — vision was declared "an explicit non-goal".
2. `factory.build_provider` never threaded `supports_vision` for `claude_code`,
   so an operator who set `SLACKS_LLM_SUPPORTS_VISION=true` **still** got a
   vision-blind provider.

The label step's single vision call therefore always failed →
`StepFailed("provider_error")` → terminal `failed` event → the user re-types the
food as text. That is exactly the operator's report ("scanning nutrition labels
literally never works and I have to edit as text"), and it explains why the four
prior fixes never helped: #366, FTY-381 (`File.upload`), and FTY-390/402
(transient-503 retries) all targeted upload transport or retry behaviour, and
none touched whether the configured provider can read an image at all.

**"Literally never" was the tell** — a capability gap fails deterministically,
where a logic bug (a confidence gate, serving math) would have worked at least
sometimes.

Reproduced at the extraction boundary with the real provider, before any fix:

```
--- BEFORE (claude_code as shipped) ---
  RESULT: terminal StepFailed(provider_error) -> event 'failed'
--- AFTER (FTY-412 fix) ---
  RESULT: RESOLVED grams=55.0 calories=230.0 P=5.0 C=31.0 F=9.0
```

Claude Code *does* accept images — through its `stream-json` input channel — so
the fix sends them that way and threads the capability flag. No new provider, no
new DTO, no contract-shape change.

## The label used

`label-fixture-legible.png` — a nutrition panel printing **55 g serving,
230 kcal, 9 g fat, 31 g carbohydrate, 5 g protein**. Every screenshot below must
match those numbers for the scan to count as "usable".

`label-fixture-unreadable.png` — the same panel blurred until the numbers are
illegible while still recognisably a nutrition label.

## Evidence

| File | What it shows |
| --- | --- |
| `label-preview-light.png` / `label-preview-dark.png` | The picked label staged for upload, with the discard-by-default "Save this photo" toggle **off** (FTY-077 unchanged). |
| `confirm-sheet-light.png` / `confirm-sheet-dark.png` | The FTY-196/197 confirm sheet after a real scan: **230 kcal · P 5g C 31g F 9g**, `Label scan` provenance, `Not yet counted`. Matches the label exactly. |
| `counted-light.png` / `counted-dark.png` | After "Looks right": hero **230 / 1,628 kcal · 14%**, macros **P 5/131g · C 31/128g · F 9/66g**, and the timeline row counted. The user never re-typed anything. |
| `unreadable-light.png` / `unreadable-dark.png` | The illegible label scanned in-app: an honest **"Add a detail ›"** row that visibly invites follow-up — not a silently-wrong entry, not a terminal `failed`. Day totals stay at 230, unaffected. |

## How it was produced

1. Leased a dedicated simulator (`sim-slot acquire --label FTY-412`); all
   `simctl`/Maestro work targeted that UDID, never `booted`.
2. Ran the API from this worktree on port 8412 with
   `SLACKS_LLM_PROVIDER=claude_code` and `SLACKS_LLM_SUPPORTS_VISION=true`
   (SQLite; the label path is synchronous, so no worker/broker is involved).
3. Seeded both label photos into the simulator's photo library
   (`simctl addmedia`) — the simulator has no camera, which is exactly the
   FTY-381 "Choose from Library" path.
4. Drove the real UI with Maestro: connect → sign in → onboarding → Today →
   label capture → Choose from Library → Upload → confirm.

Server-side confirmation from the same run:

```
POST /api/users/<uid>/log-events/label?save=false            201 Created
GET  /api/users/<uid>/log-events/<id>/label-proposal         200 OK
POST /api/users/<uid>/log-events/<id>/label-proposal/confirm 200 OK
```

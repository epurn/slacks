---
id: FTY-103
state: ready_with_notes
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - mobile
  - onboarding
  - goal
  - target-reveal
  - routing
approved_dependencies:
  - FTY-097
  - FTY-091
  - FTY-090
  - FTY-106
  - FTY-127
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/target-calculator.md
  - docs/contracts/identity-and-profile.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - step-flow-and-back-navigation
  - auto-detect-units-timezone-defaults
  - target-reveal-provenance
  - signin-onboarding-today-vs-returning-routing
  - accessibility
autonomous: true
---

# FTY-103: Onboarding Flow Redesign (Goal-Led, With Target Reveal)

## State

ready_with_notes

> **Gating note (read before promoting to `ready`):** this story is the
> **mobile-core** half of a two-boundary feature. The goal-led flow's step 1
> (goal + pace) and step 3 (target reveal) require a backend **goal-creation +
> target-reveal endpoint that does not exist yet** — FTY-022 shipped the target
> *calculator* and the `goals` / `daily_targets` tables, but **no HTTP route**
> creates a goal or computes/returns a target (see Dependencies → FTY-106). This
> story consumes that endpoint; it must be authored and merged first. The mobile
> slice below is fully specified and ready in shape — it is held at
> `ready_with_notes` only because its backend prerequisite is not yet written.

## Lane

mobile-core

## Dependencies

- **FTY-127 (NEW, backend-core — release-audit blocker; must merge before this
  re-opens for review):** the reviewer (run 2, 2026-06-29) found that the
  completeness gate's `getTarget` probe is **day-scoped** — `GET /target` 404s on
  any day after goal creation because a `daily_targets` row is only materialised
  on creation day. The gate maps that 404 to "incomplete" and re-onboards a
  fully-onboarded returning user, and re-completing the wizard resets
  `start_weight`/`start_date` (trajectory corruption). There is **no goal-existence
  / onboarding-status read endpoint** (the goals router is `POST /goal` only), so
  this gate cannot be fixed standalone. FTY-127 makes `GET /target` return the
  carried-forward target for **every in-horizon day**, so the returning-user probe
  reads `present` and routes to Today. **PR #101 is held as draft until FTY-127
  merges**; the FTY-103 fix then only needs the returning-user-on-a-later-day
  integration test (the existing gate logic is correct once the backend is fixed).
- **FTY-106 (NEW, backend-core — must be created and merged first):** the
  **goals + target-reveal endpoint** this flow writes the goal to and reads the
  computed target from. FTY-022 (merged) provides the deterministic calculator
  (`compute_daily_target`) and the `goals` / `daily_targets` schema, but it is
  **not reachable over HTTP**: there is no goals router, `compute_daily_target`
  requires a pre-existing `goal_id` that only tests create directly, and the
  daily-summary endpoint merely *reads* a stored `daily_targets` row (or returns
  `null`). A real goal-led onboarding therefore needs a backend route that (a)
  creates the user-owned goal from goal-direction + pace + start weight, (b)
  triggers `compute_daily_target`, and (c) returns the computed target with its
  provenance for the reveal. That is a separate serializing boundary (backend
  code) **and** a new public contract — pulled out as FTY-106 rather than bundled
  here. **This story is blocked until FTY-106 merges.**
- **FTY-097 (design system):** onboarding is rebuilt against FTY-097's tokens
  (color/spacing/type/components — amber accent, charcoal dark surface, the
  bespoke hero numeral face). The current onboarding is the hardcoded-style
  `ProfileForm` (FTY-021); this story re-skins and restructures it on tokens.
- **FTY-091 (sign-in / create-account):** onboarding follows sign-in. FTY-091
  owns the signed-out → sign-in screen and the post-auth landing; this story
  inserts onboarding between successful auth and Today for a new user.
- **FTY-090 (session token store):** the returning-user skip-to-Today path
  consumes `useSession()` (persisted session). This story does not touch session
  plumbing; it reads it for routing.
- Builds on **merged FTY-021** (profile capture — the measurements step reuses
  its field set and canonical-unit conversion) and **merged FTY-022** (the target
  calculator the reveal surfaces, via FTY-106).

## Outcome

A new user, immediately after creating an account (FTY-091), is walked through a
calm, goal-led **3-step onboarding** and lands on Today with a real, derived
calorie target — captured the way the design's §3 specifies:

1. **Goal + pace** — pick a direction (lose / maintain / gain) and a pace; this
   is the goal the target calculation needs.
2. **Measurements** — the body metrics the metabolic formula needs (height,
   weight, birth year, formula variant), with **units and timezone auto-detected**
   from the device locale (not asked).
3. **Target reveal** — the moment the computed daily calorie target is shown
   **with its provenance** ("└ from your goal + your metrics"), then → Today.

A **returning user** (persisted session via FTY-090, onboarding already
completed) **skips straight to Today** — onboarding never re-runs. The flow is
rebuilt on FTY-097's design tokens, replacing the functional-scaffold styling of
the current profile form.

This closes the design's §3 onboarding gap: the app currently captures profile
metrics (FTY-021) but never captures the *goal*, never reveals the target, and
opens to a status screen with a `null` target.

## Scope

- **Build the 3-step onboarding flow** as a token-styled (FTY-097) mobile-core
  feature, routed between sign-in and Today. Use a new route / step container
  under `mobile/app/` (e.g. `app/onboarding.tsx` or an onboarding stack);
  register it on the existing `_layout.tsx` Stack. A clear linear stepper with
  **back navigation** between steps; forward only when the current step is valid.
- **Step 1 — Goal + pace.** Capture goal direction (lose / maintain / gain) and a
  **pace** preset. Send the goal to FTY-106's goal-creation endpoint (which owns
  the pace → trajectory math and persists the `goals` row). Pace presets are
  **evidence-based** (see Planning Notes): offer gentle / steady / faster bands
  expressed as ~% bodyweight/week, **default to the steady (~0.5%/wk) option**,
  and never offer a default more aggressive than ~1%/wk. Maintain hides the pace
  control. The authoritative safety clamp stays server-side (the calculator's
  1200/1500 kcal floor); the UI's job is to not *invite* an unsafe choice.
- **Step 2 — Measurements.** Capture the calculator's body inputs — height,
  weight, birth year, and the metabolic-formula **variant** (the existing
  `mifflin_st_jeor_plus5` / `mifflin_st_jeor_minus161` choice; the unspecified
  placeholder is never written, per the identity-and-profile + target-calculator
  contracts). Reuse FTY-021's validation + canonical-unit conversion
  (`@/state/profile`); write via the existing `PUT /api/users/{id}/profile`.
  **Units auto-detect from the device locale** (metric/imperial) and **timezone
  auto-detects** from the device IANA zone — both captured silently (shown
  read-only, adjustable later in Profile per §4c), not asked as questions.
- **Step 3 — Target reveal.** After the goal + measurements are saved, request the
  computed target from FTY-106 and present it as the reveal: the daily calorie
  target prominently (hero-numeral treatment per FTY-097), **with a provenance
  line** ("└ from your goal + your metrics") honoring the "every number shows
  where it came from" principle. A primary action continues to **Today**. Handle
  the `clamped` case honestly (the calculator may clamp an aggressive plan to the
  safety floor) — surface a calm note rather than a silent number.
- **Routing.** Wire the flow into the app's entry routing:
  - signed-out → sign-in (FTY-091 owns this);
  - signed-in **but onboarding not complete** (new account: incomplete profile or
    no active goal) → onboarding;
  - signed-in **with onboarding complete** (returning, persisted session +
    existing goal/profile) → **Today**, skipping onboarding.
  The "onboarding complete" gate reads existing state (profile completeness via
  `GET profile`, active-goal/target state via FTY-106 / daily-summary
  `target != null`); the exact primitive is an implementation choice but must be
  loop-free and must not re-run onboarding for an established user.
- Honor the **pre-v1 clean-break** stance: build the clean goal-led flow; no
  compat shim for the old goal-less profile-only entry.

## Non-Goals

- **The target calculator itself** (merged FTY-022) and **the backend
  goal-creation + target-reveal endpoint** (FTY-106) — consumed, not built here.
  No backend code in this story.
- **Macro targets** (FTY-094) — the reveal shows the calorie target only; macros
  are out of the FTY-022 contract.
- **Sign-in / create-account screens and session plumbing** (FTY-090 / FTY-091) —
  this story routes *from* sign-in and *reads* the session; it does not build
  either.
- **Design tokens / component library** (FTY-097) — consumed, not defined.
- Editing goal/pace/metrics *after* onboarding (the Profile "control panel" §4c
  and its mini target-reveal on edit) — a later story; this is first-run only.
- Self-host server connect / QR (§4d) — separate.

## Contracts

- **Introduces no new contract in this story.** It consumes: the existing
  identity-and-profile profile DTO (`PUT /api/users/{id}/profile`), the
  **FTY-106 goal-creation + target-reveal endpoint** (whose contract FTY-106
  defines), and the target-calculator output semantics (FTY-022) it renders. The
  new public contract for goal creation + target reveal belongs to **FTY-106**,
  not here — that boundary split is why this story stays a clean mobile slice.

## Security / Privacy

- Writes only the **user's own** profile and goal, over the authenticated API
  (bearer token from FTY-090); object-level ownership is enforced server-side
  (fail-closed `404`, per both contracts). No new trust boundary, no untrusted
  input, no provider secret on the client.
- Body metrics (height, weight, birth year) and the derived target are sensitive
  personal data: entered by the owner, sent only over the authenticated API, and
  **never logged** (mirrors `ProfileForm` / `profile.ts` and the daily-summary
  no-log-personal-numbers rule).
- Medium risk: a multi-step flow that writes profile + goal and gates app entry
  routing, but no credential handling (FTY-090/091 own that), no new contract or
  schema (FTY-106 owns those), and no new untrusted-input boundary.

## Acceptance Criteria

- From a freshly created account (FTY-091), the app enters **onboarding** and
  presents the three steps in order: goal + pace → measurements → target reveal.
- Step 1 captures a goal direction and (for lose/gain) a pace; **maintain** hides
  pace; the **default pace is the steady (~0.5%/wk) option** and no offered
  default exceeds ~1%/wk. The goal is persisted via FTY-106.
- Step 2 captures height, weight, birth year, and a metabolic-formula **variant**
  (never the unspecified placeholder), validating via FTY-021's logic and writing
  the canonical (metres/kg) payload to `PUT profile`. **Units and timezone are
  auto-detected** from the device and shown read-only, not asked as questions.
- Step 3 shows the **computed daily calorie target with a provenance line**
  ("from your goal + your metrics"); a `clamped` target is surfaced honestly with
  a calm note rather than presented as if unclamped. A primary action lands the
  user on **Today**, where the day's hero now shows a real (non-null) target.
- **Back navigation** moves between steps without losing entered values; forward
  is blocked until the current step validates.
- A **returning user** (persisted session, onboarding already complete) launches
  **straight to Today** — onboarding does not re-run.
- A signed-out launch routes to sign-in (FTY-091), not onboarding.
- The flow renders against **FTY-097 tokens** (light + dark), with no leftover
  hardcoded `ProfileForm` palette.
- No profile, goal, or target value appears in logs. TypeScript strict passes;
  mobile checks pass via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile), with the FTY-106 client,
  the profile client, and `useSession()` mocked:
  - **Step-flow tests:** the three steps render in order; forward is gated on
    per-step validity; **back navigation** preserves entered values; maintain
    hides the pace control; the default pace is the steady option.
  - **Auto-detect tests:** units default from a mocked locale and timezone from a
    mocked device IANA zone; both are written without a user prompt; a metric and
    an imperial locale each produce the correct canonical payload.
  - **Goal + measurement write tests:** step 1 calls FTY-106's goal-create with
    the selected direction/pace; step 2 PUTs the canonical profile payload with a
    concrete formula variant (never the placeholder).
  - **Target-reveal tests:** the reveal renders the returned target with the
    provenance line; a `clamped` response surfaces the calm clamp note;
    "Continue" routes to Today.
  - **Routing tests:** signed-out → sign-in; signed-in + onboarding-incomplete →
    onboarding; signed-in + onboarding-complete (returning) → Today (no re-run);
    the gate does not loop.
  - **Accessibility:** labelled controls, an accessible stepper / back affordance,
    VoiceOver-coherent provenance on the reveal (per §7), ≥44pt targets, both
    color schemes meet contrast.
  - Assert no profile/goal/target value is captured by a log spy.
- Run the mobile package checks (`npm run typecheck`, `npm run lint`, `npm run
  test` in `mobile/`, via `make verify` where wired).
- On an iOS simulator (once FTY-106 + FTY-097 + FTY-091 are merged): create an
  account → complete onboarding → confirm Today shows a real target; relaunch to
  confirm the returning session skips straight to Today.

## Planning Notes

- **The backend gap is the headline.** `backend/app/services/targets.py`
  (`compute_daily_target`) and `backend/app/schemas/goals.py` /
  `models/targets.py` exist and are tested, but `main.py` registers **no goals or
  targets router**, and `compute_daily_target` takes an already-persisted
  `goal_id`. Onboarding cannot "consume an existing endpoint" because there isn't
  one — hence FTY-106. Do not let the author attempt a backend route from this
  story; that would cross the boundary and breach the single-lane rule.
- **No client-side target math.** The reveal must show the *authoritative*
  backend-computed target (provenance + the safety clamp live in the FTY-022
  calculator). Re-deriving the NIDDK math on-device would duplicate the estimator
  and break "every number shows where it came from." The reveal reads FTY-106's
  output; it computes nothing.
- **Evidence-based pace presets (research-grounded).** A safe, lean-mass-sparing
  weight-loss rate is **~0.5–1% of body weight per week** (≈0.5–1 kg/wk, the
  NIH/NIDDK ~500–1000 kcal/d deficit guidance); rates **above ~1.5%/wk** measurably
  increase lean-mass loss and metabolic adaptation, so gentler is better for
  adherence and body composition. This **overrides** the intuitive "faster is
  better" framing a generic diet app would default to: onboarding should
  **default to the steady ~0.5%/wk option** and cap the offered presets so no
  default invites >~1%/wk. Lean **gain** is far slower (≈0.25–0.5 lb/wk), so the
  gain presets are correspondingly gentler. The hard safety backstop remains the
  calculator's 1200/1500 kcal floor (it clamps and flags an over-aggressive plan).
  The exact pace→trajectory conversion (pace + start weight → `target_date`)
  belongs to FTY-106's contract; FTY-103 only presents the presets and sends the
  chosen one.
- **Measurements step reuse:** `mobile/components/ProfileForm.tsx` +
  `@/state/profile` already encode the field set, validation, canonical-unit
  conversion, locale-defaulted units, and device-timezone capture. Restructure
  these into onboarding's step 2 on FTY-097 tokens rather than re-deriving them;
  keep the canonical (metres/kg) payload and the two-variant formula rule.
- **Formula-variant subtlety:** §3 says the metabolic formula "provides sensible
  defaults," but the calculator **rejects** the unspecified `mifflin_st_jeor`
  placeholder — a concrete `+5` / `-161` variant must be chosen before a target
  can be computed. Keep the formula-variant selection in step 2 (as FTY-021 does);
  do not silently auto-pick a sex-dependent constant. Flagged as a product gap
  below.
- Routes today: `app/index.tsx` (Today), `app/profile.tsx`, plus `app/signin.tsx`
  (FTY-091). Add the onboarding route on the same `_layout.tsx` Stack (built to
  take new screens without restructuring, per FTY-013).

## Readiness Sanity Pass

- **Product decision gaps to resolve before promotion:** (1) whether step 2 keeps
  an explicit formula-variant choice (recommended — the calculator requires a
  concrete variant) or hides it behind a default; (2) the exact pace preset labels
  and bands (recommended evidence-based: gentle ~0.25%/wk · steady ~0.5%/wk ·
  faster ~0.75–1%/wk for loss, default steady; gentler for gain) — these may be
  co-owned with FTY-106's contract; (3) the "onboarding complete" routing signal
  (profile-complete + active-goal vs. an explicit flag) — recommended derived, not
  a new field; (4) target-reveal copy for the normal and `clamped` cases.
- **Cross-lane impact / sizing decision (the load-bearing call):** the *feature*
  spans two serializing boundaries — **mobile-core** (this flow/UI/routing) and
  **backend-core** (a new goal-creation + target-reveal endpoint, which is also a
  **new public contract** — a big rock). Per the scope guardrail I **refused to
  write this as one story** and **returned the split**: FTY-106 (backend
  prerequisite, the endpoint + contract) and this narrowed FTY-103 (mobile
  dependent, depends on FTY-106). FTY-103 itself is a clean single mobile-core
  boundary: `review_focus` 5 (at the ceiling), `requires_context` 5 (under 8), no
  second code lane, no big rock. The "consumes existing endpoints, none new"
  premise in the request was factually incorrect — the endpoint doesn't exist —
  which is exactly what forced the split.
- **Security/privacy risk:** medium — writes the owner's own profile + goal over
  the authenticated API with server-side fail-closed ownership; sensitive body
  metrics and target never logged; no credential handling, no new contract/schema,
  no new untrusted-input boundary (those live in FTY-090/091/104).
- **Verification path:** mobile step-flow / auto-detect / goal+measurement-write /
  target-reveal / routing / accessibility tests against mocked FTY-106 + profile
  clients + `useSession()`, plus a post-merge simulator create→onboard→relaunch
  smoke check and `make verify`.
- **Evidence basis captured:** pace presets grounded in the ~0.5–1%/wk safe
  weight-loss-rate evidence (NIH/NIDDK deficit guidance; >1.5%/wk harms lean mass),
  recorded in Planning Notes, overriding the generic "faster is better" default.
- **Assumptions safe for autonomy:** yes for the mobile slice **once FTY-106,
  FTY-097, and FTY-091 are merged** and the four product gaps above are confirmed.
  Until FTY-106 exists this is held at `ready_with_notes` (not `ready`): the
  backend prerequisite must be authored first. To promote to `ready`: create and
  schedule FTY-106, confirm the gaps, and flip the state.

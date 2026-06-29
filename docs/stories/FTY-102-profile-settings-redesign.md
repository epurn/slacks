---
id: FTY-102
state: merged
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - profile
  - settings
  - targets
  - provenance
  - override
  - macros
  - appearance
  - weigh-in-cadence
  - mobile
approved_dependencies: []
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/identity-and-profile.md
  - docs/contracts/target-calculator.md
  - docs/contracts/daily-summary.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
review_focus:
  - target-provenance-override-reset
  - macro-target-provenance-override-reset
  - mini-target-reveal-on-goal-or-metric-edit
  - appearance-light-dark-via-tokens
  - own-profile-sensitive-data-handling
autonomous: true
---

# FTY-102: Profile / Settings Redesign — "Control Panel for Your Numbers"

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-097 (design system / tokens — this screen is rebuilt entirely against the
  FTY-097 token set: type, spacing, color, light/dark, grouped-list components).
- FTY-094 (macro targets — supplies the macro-target values + their provenance in
  the daily-summary / target surface this screen displays).
- FTY-095 (calorie + macro override + reset — supplies the override/reset write
  surface and the "set by you" vs. "derived" provenance state this screen renders
  and drives).
- FTY-022 (target calculator: `goals` + `daily_targets` and the goal/target write
  + recompute surface that the mini target-reveal triggers and reads back).
- FTY-021 (mobile profile capture — **merged**; reuse its body-metric editors,
  units-aware display, and profile read/write client).
- FTY-090 (mobile session token store — sign-out clears the session through it).

## Outcome

The mobile Profile / Settings screen is rebuilt as a **control panel for your
numbers** (UX design §4c), not a generic settings dump. It opens from the
persistent header gear as a native grouped settings screen and **leads with the
numbers the whole app depends on**, in this order:

- **YOU** — Goal (lose / maintain / gain + pace), Calorie target shown **with its
  provenance** ("└ from your goal + metrics") and a clearly-marked manual override
  ("✎ set by you") with a **Reset** to the derived value, and the macro targets
  shown with the same provenance + override + reset treatment.
- **BODY** — the metabolic-formula inputs: weight, height, age, and biological sex
  (carried by `metabolic_formula`). Editing any of these recomputes the derived
  target with a **mini target-reveal**.
- **PREFERENCES** — units (locale auto-detect, overridable), appearance
  (Light / Dark / System), and notifications including the **weigh-in cadence**
  (Weekly default · Every 2 weeks · Monthly · Off). Minimal and calm: no
  daily-logging nag, no streaks.
- **ACCOUNT & SERVER** — sign-in / session state, the self-host server connection,
  and sign out.
- **DATA & ABOUT** — data export / account deletion entry points and about /
  version.

Editing the goal/pace or any body metric recomputes the derived calorie target
(and macro targets) via the FTY-022/094/095 surface and surfaces the change with a
mini target-reveal; a manual override is honestly marked and resettable. Every
number on this screen shows where it came from — the "every number shows where it
came from" principle applied to the target itself.

## Scope

Rebuild the existing Profile / Settings screen (the merged FTY-021 surface)
against FTY-097 tokens and components. All work is mobile presentation +
client-side wiring consuming already-specified contracts; this story adds no
server logic and no new contract.

**Layout & frame**
- Native grouped settings layout opened from the header gear, with the five groups
  in the order above (YOU → BODY → PREFERENCES → ACCOUNT & SERVER → DATA & ABOUT).
- Built entirely from FTY-097 tokens/components (type scale, spacing, grouped-row,
  color, light/dark surfaces); no ad-hoc styling. Renders correctly in light and
  dark.

**YOU — the numbers, with provenance**
- Render the **calorie target** with its source line: derived shows
  "└ from your goal + metrics"; a manual override shows "✎ set by you" plus a
  **Reset** affordance that returns it to the derived value. Override and reset
  drive the FTY-095 write surface; the displayed value + provenance reconcile to
  the read-back.
- Render the **macro targets** (P / C / F) with the same provenance + override +
  reset treatment, sourced from FTY-094 and FTY-095. These are exactly what the
  Today P/C/F chips measure against (FTY-094 / `daily-summary.md`).
- Render the **goal** (direction lose/maintain/gain + pace). Editing goal/pace
  writes through the FTY-022 goal surface and triggers a recompute.

**BODY — metabolic inputs (reuse FTY-021)**
- Edit weight, height, age (via `birth_year`), and biological sex (via the two
  computable `metabolic_formula` variants — `mifflin_st_jeor_plus5` / `…minus161`,
  per `identity-and-profile.md` / `target-calculator.md`), reusing FTY-021's
  units-aware editors and profile read/write client. Canonical units cross the API
  boundary only (metres / kilograms); display follows the units preference.

**Mini target-reveal**
- After a goal/pace or body-metric edit recomputes the derived target, surface the
  new calorie target (and macro targets) with a compact **mini target-reveal**
  (a small reveal of the updated number, calm, no full-screen takeover), reading
  the recomputed values back from the FTY-022/094 surface. If the derived value
  was clamped to the safety band (`clamped`, per `target-calculator.md`), the
  reveal reflects the clamped value honestly.

**PREFERENCES**
- **Units**: auto-detect from locale, overridable (metric/imperial; kg/lb; kcal),
  persisted via the existing `units_preference` profile field (FTY-021).
- **Appearance**: Light / Dark / System override, persisted **on-device** (a
  display preference; no server field), applied through FTY-097's light/dark
  tokens.
- **Notifications / weigh-in cadence**: a cadence control (Weekly default · Every
  2 weeks · Monthly · Off) persisted **on-device**, driving a low-frequency
  weigh-in reminder that fires only when a reading is due — never daily, no
  streaks, no daily-logging nag (UX §4b "Encourage the trend, not the scale";
  default Weekly is the design-doc evidence-based default — daily weighing confers
  no added weight-loss benefit and ~4 readings/month is plenty for a meaningful
  trend). The "Off" option fully disables the reminder.

**ACCOUNT & SERVER**
- Show sign-in / session state and the connected self-host server, linking to the
  connect / sign-in surfaces (FTY-090 / FTY-091 / §4d) — this screen does not
  implement those screens.
- **Sign out** clears the persisted session through FTY-090's session token store
  and returns the app to the unauthenticated entry state.

**DATA & ABOUT**
- Render the data export and account-deletion entry points (rows that route to
  their flows) and an about / version row. Actual export and account-deletion
  backends are out of scope (see Non-Goals); the rows are present and wired to
  their destinations / stubs.

**Cross-cutting**
- Sensitive figures (targets, macros, body metrics) are shown only to the
  authenticated owner over the existing authenticated client and are never written
  to logs, errors, or analytics.
- Loading / error / empty states render sensibly (e.g. target not yet computable
  for an incomplete profile shows a calm "set your goal + metrics" prompt rather
  than a broken number, consistent with `target-calculator.md`'s incomplete-profile
  rule).
- Accessibility: VoiceOver labels on every provenance marker and on each editable
  number, ≥44pt targets, full Dynamic Type, never color as the sole signal,
  respects Reduce Motion (the mini target-reveal degrades to a simple fade).

## Non-Goals

- The calorie/macro target backend, override/reset write surface, macro-target
  derivation, or any target recompute logic (FTY-094 / FTY-095 / FTY-022) — this
  story **consumes** them.
- Design tokens / components themselves (FTY-097).
- Sign-in, create-account, and server-connect screens and the session/auth
  mechanics (FTY-090 / FTY-091 / §4d) — Profile only shows session state, links to
  those surfaces, and triggers sign-out.
- Onboarding (FTY-103) — Profile is where these inputs are edited *later*; the
  first-run capture flow is separate.
- An **activity-level** control: the profile contract has no activity field (TDEE
  uses the fixed sedentary 1.2 multiplier per `target-calculator.md`), so there is
  nothing to persist. Activity level is deferred until a backend field exists; it
  is not rendered as a dead control here. (Recorded in the Readiness Sanity Pass.)
- Implementing data export or account deletion backends/flows (separate stories) —
  only the entry-point rows are rendered here.
- Any server-side logic, endpoint, schema, or contract change.

## Contracts

- **None new.** Consumes:
  - `identity-and-profile.md` — the profile DTO and read/write API for body
    metrics, `metabolic_formula`, and `units_preference` (reused via FTY-021's
    client).
  - `target-calculator.md` — the derived calorie target, its assumptions, the
    `clamped` safety-band flag, and the goal trajectory inputs (FTY-022).
  - `daily-summary.md` + FTY-094/FTY-095 fields — the macro targets and the
    target/macro provenance + override/reset state this screen renders and drives.
- Appearance and weigh-in-cadence preferences persist on-device (no server
  contract); units persists via the existing `units_preference` profile field.

## Security / Privacy

- The screen edits the **user's own** profile and targets only, over the existing
  authenticated client (TLS); object-level authorization is enforced server-side
  (own-profile-only, fail-closed per `identity-and-profile.md`). No cross-user
  access path is introduced.
- Sensitive values (body metrics, calorie/macro targets) are never written to
  logs, error messages, or analytics; errors carry only status + endpoint,
  mirroring the FTY-021 profile client.
- Sign-out clears the persisted session through FTY-090's secure session store; no
  session material is left behind.
- No new sensitive on-device storage beyond the on-device display preferences
  (appearance, weigh-in cadence), which are non-sensitive UI settings.
- Medium risk: several sensitive numbers and an override/reset write path on the
  user's own data, but no server logic of its own.

## Acceptance Criteria

- Profile / Settings opens from the header gear as a native grouped screen with the
  five groups in order (YOU → BODY → PREFERENCES → ACCOUNT & SERVER → DATA & ABOUT),
  built from FTY-097 tokens, rendering correctly in **both light and dark**.
- The calorie target renders with its provenance: derived shows the
  "from your goal + metrics" source line; an override shows "✎ set by you" with a
  working **Reset** that returns it to the derived value (driven through FTY-095,
  reconciled on read-back).
- The macro targets (P/C/F) render with the same provenance + override + reset
  treatment, sourced from FTY-094/095.
- Editing goal/pace or any body metric (weight / height / age / sex) recomputes the
  derived target and surfaces the change with a **mini target-reveal** showing the
  updated calorie and macro targets; a clamped value is shown honestly.
- An incomplete profile (target not yet computable) shows a calm prompt rather than
  a broken or fabricated number.
- Units override persists via `units_preference`; appearance (Light/Dark/System)
  and weigh-in cadence (Weekly default · Every 2 weeks · Monthly · Off) persist
  on-device and take effect; the reminder is low-frequency and "Off" disables it —
  no daily reminder, no streaks.
- Account & Server shows session/server state and links to the FTY-090/091 surfaces;
  **Sign out** clears the session via FTY-090 and returns to the unauthenticated
  state. Data & About renders export/deletion entry rows + an about/version row.
- No sensitive value (target, macro, body metric) appears in logs or error output.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile):
  - Component tests for the **calorie-target provenance/override/reset** row:
    derived source line; "✎ set by you" override state; Reset returns to derived
    (FTY-095 mock); displayed value reconciles to read-back.
  - Component tests for the **macro-target** rows: provenance + override + reset
    against FTY-094/095 mocks.
  - Test the **mini target-reveal**: a goal/pace edit and a body-metric edit each
    trigger a recompute (mocked FTY-022/094 surface) and reveal the updated
    calorie + macro targets; a `clamped` result is rendered honestly; incomplete
    profile shows the calm prompt, not a broken number.
  - Test the **settings groups in light and dark**: the five groups render in both
    color schemes via FTY-097 tokens with no hard-coded colors.
  - Test PREFERENCES persistence: units writes `units_preference`; appearance and
    weigh-in cadence persist on-device and apply; "Off" disables the reminder; no
    daily/streak reminder is scheduled.
  - Test **Sign out** clears the session via a mocked FTY-090 store and routes to
    the unauthenticated state; Account/Data rows route to their destinations.
  - Assert no sensitive value is emitted to logs/errors.
  - Accessibility checks: VoiceOver labels on provenance markers and editable
    numbers; Reduce-Motion path for the mini target-reveal.
- Run mobile typecheck, lint, and tests via `make verify` (delegates to the mobile
  package: `tsc --noEmit`, `eslint .`, `jest`).
- On an iOS simulator: open Profile from the gear, edit a body metric and confirm
  the mini target-reveal updates the calorie + macro targets, override a target and
  reset it, toggle appearance and weigh-in cadence, and sign out — in both light and
  dark.

## Planning Notes

- This is the §4c slice of the resolved whole-product UX design; it implements that
  design rather than re-deciding it. The weigh-in-cadence default (Weekly) and the
  "no daily nag / no streaks" stance are the design doc's evidence-based decision
  (§4b) — embedded here, not re-litigated.
- It builds on merged FTY-021 (profile capture): reuse its body-metric editors,
  units handling, and profile client rather than re-implementing them.
- Targets, macros, override/reset, and goal recompute are all **consumed** from the
  FTY-094 / FTY-095 / FTY-022 backend surfaces; if any is not yet merged, that is a
  dependency note — the screen builds against their published fields.
- Appearance and weigh-in-cadence as on-device preferences (no new server field)
  keeps this a single mobile-core boundary with no contract change.

## Readiness Sanity Pass

- **Product decision gaps:** none blocking — §4c/§4b settle the layout, the
  number-leading order, provenance/override/reset, the mini target-reveal, and the
  weigh-in-cadence default. One scope decision recorded: **activity level is not
  rendered** because the profile contract has no activity field (TDEE is fixed at
  the 1.2 sedentary multiplier per `target-calculator.md`); it is deferred to a
  future backend field rather than shipped as a dead control. Appearance + weigh-in
  cadence persist on-device (no server field needed).
- **Cross-lane impact:** none. Single boundary = **mobile-core**. No public
  contract change (consumes existing `identity-and-profile.md`, `target-calculator.md`,
  `daily-summary.md` + FTY-094/095 fields), no schema migration, no new
  untrusted-input trust boundary. Security/privacy rides along (non-serializing) and
  is not a second boundary.
- **Sizing:** one author run, one screen rebuilt against existing contracts. At the
  `review_focus` ceiling (5 concerns) but not over it; `requires_context` = 7 (under
  the 8 ceiling). No big rock bundled → kept as a single story, not split.
- **Security/privacy risk:** medium — edits the user's own sensitive profile/targets
  and drives an override/reset write path; own-profile-only authorization is enforced
  server-side, no value logging, sign-out clears the session via FTY-090, no new
  sensitive on-device storage.
- **Verification path:** mobile component tests (target + macro provenance/override/
  reset, mini target-reveal incl. clamped + incomplete-profile, light/dark groups,
  preferences persistence, sign-out), accessibility checks, `make verify`, and a
  simulator smoke check in both color schemes.
- **Assumptions safe for autonomy:** yes. Dependency note: FTY-094 / FTY-095 / FTY-097
  may not all be merged yet — the slice builds against their published token set and
  fields; FTY-021 (reused) is merged.

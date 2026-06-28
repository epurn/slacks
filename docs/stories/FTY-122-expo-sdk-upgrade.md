---
id: FTY-122
state: candidate
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - mobile
  - expo
  - dependencies
  - toolchain
  - upgrade
approved_dependencies: []
requires_context:
  - mobile/package.json
  - docs/standards/testing-standards.md
  - docs/standards/coding-standards.md
  - docs/architecture/repo-layout.md
review_focus:
  - sdk-set-coherence
  - ci-green-lint-and-jest
  - no-app-behaviour-regression
  - dependency-justification
autonomous: true
---

# FTY-122: Upgrade the Expo SDK (move the pinned toolchain coherently) (mobile-core)

## State

candidate

<!-- DEFERRED: the app is already on the newest stable Expo SDK (56, released
     2026-05-21). There is no newer stable SDK to upgrade to yet — SDK 57 is not
     released (not even beta) as of 2026-06-28. This story is NOT assignable
     (`candidate`, outside READY_STATES) until Expo ships the next stable SDK.
     Promote to `ready` when SDK 57 (or later) lands; that release is also when
     the deps in the closed dependabot PRs (RN 0.86, jest 30, eslint 10) first
     become installable. -->

## Trigger

Promote to `ready` when a stable Expo SDK newer than 56 is released. Until then
the mobile toolchain is already at the latest coherent pinned set and there is
nothing to upgrade.

## Lane

mobile-core

## Dependencies

- None blocking. Operates on the merged mobile app on `main`.

## Related

<!-- Cross-reference only — NOT a scheduling dependency. Kept out of the
     Dependencies section above so the steward's metadata_dependencies parser
     does not read this ID as a blocker (which would deadlock 121 <-> 122). -->

- **FTY-121** (Dependabot ignore rules) stops the doomed individual SDK-governed
  PRs; this story is the supported path by which those same packages actually
  advance. Either order is fine.

## Outcome

**Deferred until a newer stable SDK exists** (see Trigger): as of 2026-06-28 the
app is already on the newest stable Expo SDK (56), so there is nothing to upgrade
*yet*. When Expo ships the next stable SDK, this story executes.

When triggered, the mobile app moves off its **current** Expo SDK onto the **new
latest stable Expo SDK** as a single coherent upgrade, so the SDK-governed
toolchain — `react`, `react-native`,
`react-test-renderer`, `react-dom`, `jest`, `jest-expo`, `@types/jest`, and the
eslint stack — all move **together** to the versions that SDK pins, with mobile
CI (lint + jest) green. This is the **only** mechanism by which the bumps in the
four dependabot PRs closed on 2026-06-28 (react patch, react-native minor, jest
30, eslint 10) legitimately land: they failed precisely because each tried to
move one SDK-governed package in isolation (peer `ERESOLVE` / `jest-expo` preset
breakage / `eslint-plugin-react` incompatibility). Taking them via the SDK
upgrade resolves the whole set at once against versions Expo has validated to work
together.

## Scope

- **Upgrade the Expo SDK from 56 to the latest stable**, using the supported Expo
  upgrade flow rather than hand-editing versions:
  - Bump the `expo` package to the latest stable SDK, then run
    `npx expo install --fix` so every Expo-managed dependency (`react`,
    `react-native`, `react-dom`, `react-test-renderer`, `jest-expo`, `jest`,
    `@types/jest`, and the other SDK-pinned libs) is realigned to the versions the
    new SDK requires. Follow the official Expo SDK upgrade guide for that target
    SDK for any manual steps it calls out.
  - Regenerate `mobile/package-lock.json` cleanly (a fresh, ERESOLVE-free install
    tree) so the lockfile matches the new pinned set.
- **Realign the test + lint toolchain to the new SDK:**
  - Update `jest-expo` (and the `jest` preset wiring) to the SDK-pinned versions
    so the `jest-expo` preset loads and the existing mobile test suite runs.
  - Update the eslint toolchain (`eslint`, `eslint-plugin-*`,
    `@typescript-eslint/*`, and `eslint-config-expo` if present) to the
    SDK-compatible versions so lint passes — the eslint 10 / `eslint-plugin-react`
    incompatibility that sank the dependabot PR is resolved by moving the whole
    config together, not eslint alone.
  - Apply the **minimal** config/syntax migrations the new majors force (e.g. an
    eslint flat-config or rule rename, a jest config key change) — only what is
    needed to make lint + jest pass, not a broader refactor.
- **Fix only the breakage the upgrade introduces.** If a renamed/removed RN or
  Expo API, a changed jest matcher, or a lint-rule change breaks a file, make the
  smallest change that restores green CI and preserves existing behaviour. Record
  any non-trivial API migration in the PR description.
- **Verify the app still builds and runs** under the new SDK (Metro bundles; the
  app boots in a simulator) — this is a toolchain move, not a feature change.

## Non-Goals

- **No new features, screens, or behaviour changes.** Purely a dependency/SDK
  move; the UI and logic are unchanged except where an API rename forces a
  mechanical edit.
- **No backend, contract, estimator, or infra changes** — mobile only.
- **No opportunistic upgrade of unrelated independent libraries** beyond what the
  SDK upgrade requires (those flow through Dependabot separately).
- **No change to the Dependabot config** — that is FTY-121.
- **No redesign of the test or lint setup** beyond the minimal migration the new
  majors require.

## Contracts

- **None.** No public product contract changes. The app consumes the same backend
  contracts as before; only its runtime/build dependency versions move.

## Security / Privacy

- **Net security-positive, mobile-only.** Moving to the latest stable SDK pulls in
  the upstream security fixes carried by the newer `react-native` / `expo` /
  toolchain releases — exactly the fixes the closed dependabot PRs were trying to
  deliver piecemeal, now applied as a validated set.
- No secrets, tokens, or private automation enter the public repo. No new external
  egress and no new trust boundary — it is a version move of existing
  dependencies. New transitive deps arrive only as pulled in by the SDK's own
  pinned set (declared by the lockfile regeneration); call out anything notable in
  the PR per FTY-013's dependency-justification rule.

## Acceptance Criteria

- `mobile/package.json` declares the latest stable Expo SDK, and `expo`, `react`,
  `react-native`, `react-test-renderer`, `react-dom`, `jest`, `jest-expo`,
  `@types/jest`, and the eslint toolchain are all at the versions that SDK pins
  (a coherent set, no peer `ERESOLVE`).
- `mobile/package-lock.json` is regenerated and installs cleanly with no peer
  resolution errors.
- Mobile **lint passes** under the upgraded eslint toolchain.
- Mobile **jest suite passes** under the upgraded `jest-expo` preset (the existing
  tests run; no preset-load failure).
- TypeScript strict typecheck passes.
- The app builds (Metro bundles) and boots in a simulator with no behaviour
  regression in the existing screens.
- `make verify` (mobile) is green; no backend/contract/infra files are modified.
- Any forced API/config migration is documented in the PR.

## Verification

- Per `docs/standards/testing-standards.md` (mobile): run mobile typecheck, lint,
  and the jest suite via `make verify` where wired — all green on the upgraded SDK.
- **Clean install check:** a fresh `npm install` (or `npm ci`) against the
  regenerated lockfile completes with no peer `ERESOLVE` error.
- **Preset check:** confirm the `jest-expo` preset loads and the test suite
  executes (the failure mode the jest-30 dependabot PR hit) — green run, not just
  collection.
- **Lint check:** confirm the eslint run completes under the new toolchain (the
  failure mode the eslint-10 PR hit) — no plugin/config load error.
- **Simulator smoke:** Metro bundles and the app boots; spot-check the primary
  screens render and basic navigation works (no behaviour regression).

## Planning Notes

- **Use `expo install --fix`, not manual version edits.** The whole reason the
  individual dependabot PRs failed is that the SDK pins a mutually-compatible set;
  the Expo tooling resolves that set. Hand-pinning risks re-introducing the same
  ERESOLVE.
- **Target the latest stable SDK** at implementation time (SDK 57+ as available);
  follow that SDK's official upgrade guide for required manual steps (config
  plugin changes, RN new-architecture notes, etc.). If a clean jump to the latest
  is blocked by a hard incompatibility, stepping one SDK at a time is an
  acceptable fallback — note which target was reached and why.
- **Risk is the breadth, not the depth.** A single serializing lane, but it
  touches react-native, the jest preset, and the eslint majors at once, any of
  which can force a mechanical migration. Marked **medium**; CI (lint + jest +
  typecheck) is the objective gate, and the blast radius is contained to mobile.
- No evidence research warranted — this is a toolchain/upgrade decision dictated
  by Expo's SDK pinning, not a health/nutrition/behavioural question.

## Readiness Sanity Pass

- **Product decision gaps:** none on the work itself. But the app is already on
  the newest stable SDK (56), so there is no upgrade target today — this is
  **`candidate` (deferred)**, promoted to `ready` only when a newer stable SDK
  ships (see Trigger). The remaining judgment call — jump straight to the latest
  SDK vs. step one SDK at a time if blocked — has a documented fallback and is
  settled by what CI accepts.
- **Sizing decision:** one boundary — **mobile-core** only. No code in a second
  serializing lane. **Zero big rocks:** no public contract change (consumes the
  same backend contracts), no schema migration, no new untrusted-input trust
  boundary — a version move of existing deps plus the minimal forced migrations.
  `review_focus` = 4 (under 5); `requires_context` = 4 (under 8). One story.
  Although it touches several majors, they must move *together* (the SDK is the
  serializing unit) — splitting per-package is exactly the failure mode that
  closed the dependabot PRs, so this stays one coordinated story.
- **Cross-lane impact:** none beyond mobile-core. No backend/contract/estimator/
  infra files touched.
- **Security/privacy risk:** medium — security-positive (newer upstream releases),
  but a broad dependency move with mechanical-migration potential; CI gates it. No
  secrets cross into the public repo; no new trust boundary.
- **Verification path:** mobile typecheck + lint + jest via `make verify`, a clean
  lockfile install (no ERESOLVE), jest-expo preset load, eslint run, and a
  simulator boot/behaviour smoke.
- **Assumptions safe for autonomy:** yes — the supported `expo install --fix`
  flow with CI as the objective gate and a documented step-wise fallback. Any new
  transitive dep is declared per FTY-013's dependency rule.

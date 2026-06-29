---
id: FTY-125
state: merged
primary_lane: governance
touched_lanes: []
risk: low
tags:
  - governance
  - dependabot
  - expo
  - mobile
  - supply-chain
approved_dependencies: []
requires_context:
  - .github/dependabot.yml
  - mobile/package.json
review_focus:
  - expo-major-surfaces
  - in-sdk-noise-stays-ignored
  - schema-validity
autonomous: true
---

# FTY-125: Dependabot — Surface a New Expo SDK as the Upgrade Tripwire (governance)

## State

ready

## Lane

governance

## Dependencies

- None to schedule. Config-only edit to the existing `/mobile` `npm` ignore block
  added by merged **FTY-121**; no app code, no blocking story.

## Related

<!-- Cross-reference only — NOT a scheduling dependency. -->

- Refines merged **FTY-121** (which ignored *all* `expo` updates). This story
  narrows that single rule so a new SDK is not silently swallowed.

## Outcome

There is no Expo SDK newer than the one the app runs on today, so the coordinated
SDK upgrade is intentionally **not** a tracked story (the former FTY-122 was
dropped). The risk with that decision is forgetting: FTY-121 told Dependabot to
ignore **all** `expo` updates, so when Expo ships the next SDK, Dependabot would
stay silent and the upgrade would never surface.

This story restores a single, deliberate signal. Dependabot keeps ignoring
in-SDK `expo` **patch/minor** churn (no dead PRs), but a **major** `expo` bump —
which is exactly what a new SDK release is (e.g. `expo` 56.x → 57.x) — is allowed
through as one PR. That PR is the **upgrade tripwire**: it tells us a new SDK is
out and it is time to run the coordinated `expo install --fix` upgrade. It will
fail mobile CI (the SDK-governed peers have not moved yet); that failure is the
*expected signal*, not a regression — it is the one dead PR we want, versus the
many FTY-121 silenced.

## Scope

- **Narrow the `expo` entry in the `/mobile` `npm` `ignore:` block** of
  `.github/dependabot.yml` from "ignore all updates" to ignore only
  `version-update:semver-patch` and `version-update:semver-minor`, leaving major
  bumps un-ignored so a new SDK surfaces as a PR.
- **Leave a comment** at that entry stating the major-`expo` PR is the intentional
  SDK-upgrade tripwire and will fail CI by design (run the coordinated upgrade
  when it appears), so a future reader does not "fix" it by re-ignoring majors.
- **Everything else in the ignore block is unchanged** — `react`, `react-dom`,
  `react-native`, `react-test-renderer`, `jest`, `jest-expo`, `@types/jest` stay
  fully ignored; the eslint toolchain stays major-ignored.

## Non-Goals

- **No SDK upgrade and no dependency bumps here** — this only changes which
  update PRs Dependabot opens. The upgrade itself is a human-run `expo install
  --fix` when the tripwire fires (see the roadmap backlog note).
- **No change to other ecosystems** (`github-actions`, `uv`, `docker`) or to the
  `npm` entry's `schedule` / `open-pull-requests-limit` / `groups`.
- **No auto-merge or merge automation** for the tripwire PR — it is meant to be
  seen, then drive a manual coordinated upgrade.

## Contracts

- None. The only changed artifact is `.github/dependabot.yml`; `mobile/package.json`
  is read-only context.

## Security / Privacy

- **Net positive, config-only.** It re-enables visibility of new Expo SDK
  releases (which carry the upstream security fixes the closed dependabot PRs were
  chasing piecemeal) without re-introducing the dead in-SDK PRs. No secrets,
  tokens, or private automation enter the public repo; nothing executes until the
  surfaced bump is reviewed.

## Acceptance Criteria

- `.github/dependabot.yml` is valid YAML and a schema-valid Dependabot v2 config.
- The `/mobile` `npm` `ignore` entry for `dependency-name: "expo"` carries
  `update-types: ["version-update:semver-patch", "version-update:semver-minor"]`
  (major no longer ignored).
- All other ignore entries (`react`, `react-dom`, `react-native`,
  `react-test-renderer`, `jest`, `jest-expo`, `@types/jest`, and the eslint
  toolchain major rules) are unchanged.
- A comment at the `expo` entry documents the major-bump tripwire and that it
  fails CI by design.
- No dependency versions, app code, workflows, or lockfiles are modified; root
  `make verify` stays green (config-only).

## Verification

- **YAML + schema:** confirm the file parses as YAML and conforms to the
  Dependabot v2 schema (local parse + schema shape; GitHub validates
  authoritatively post-push in the repo's Dependabot config check).
- **Rule check:** assert the `expo` ignore entry lists patch + minor update-types
  and does **not** ignore majors, and that no other entry changed.
- **Regression:** root `make verify` passes (config-only).

## Planning Notes

- **Why allow the major PR even though it fails CI.** The whole point is a single
  visible signal that a new SDK exists. One predictable failing PR per SDK release
  (≈ quarterly) is the intended trade vs. silence-and-forget. It is not merged as
  is; it triggers the coordinated `expo install --fix` upgrade.
- **Why scope expo to patch+minor rather than un-ignore fully.** In-SDK `expo`
  patch/minor bumps can still fail CI (they sometimes move bundled native deps) —
  exactly the dead-PR noise FTY-121 removed. Ignoring patch+minor keeps that quiet
  while letting only the meaningful major (= new SDK) through.
- No evidence research warranted — supply-chain hygiene config, not a
  health/nutrition/behavioural question.

## Readiness Sanity Pass

- **Product decision gaps:** none. Single judgment call (which update-types to
  surface) is settled above. `ready`.
- **Sizing:** one boundary — **governance** config only. Zero big rocks (no
  contract, no migration, no new trust boundary). One story.
- **Cross-lane impact:** none beyond governance.
- **Security/privacy risk:** low — config-only, security-positive.
- **Verification path:** YAML/schema parse + rule assertion + `make verify`.
- **Assumptions safe for autonomy:** yes — a one-entry config edit with CI as the
  objective gate.

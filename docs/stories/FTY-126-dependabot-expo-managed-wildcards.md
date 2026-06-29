---
id: FTY-126
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
  - wildcard-coverage
  - tripwire-and-typescript-preserved
  - schema-validity
autonomous: true
---

# FTY-126: Dependabot — Ignore the Expo-Managed Mobile Surface by Wildcard (governance)

## State

ready

## Lane

governance

## Dependencies

- None to schedule. Config-only edit to the `/mobile` `npm` `ignore:` block in
  `.github/dependabot.yml` (added by FTY-121, refined by FTY-125); no app code, no
  blocking story.

## Related

<!-- Cross-references only — NOT scheduling dependencies. -->

- Completes merged **FTY-121** (enumerated SDK-pinned ignores) and **FTY-125**
  (the `expo` major tripwire). Those used a per-package list that leaked: PRs
  #74/#77/#78/#79 then **#83** (`@react-native/jest-preset` 0.85→0.86) all failed
  CI because an Expo-governed package not on the list was bumped in isolation.

## Outcome

In an Expo **managed** project, `expo install` governs nearly the entire JS
dependency set — every `expo-*` module, the `@react-native/*` toolchain, the
Expo-pinned `react-native-*` community libs, and the React type packages all move
as a coherent set tied to the SDK. Enumerating them one by one in Dependabot's
ignore list is whack-a-mole: each newly-pinned package leaks through as a dead PR
that fails mobile CI (the pattern that closed five PRs on 2026-06-28, the last
being #83).

This story replaces the leak-prone enumeration with **prefix wildcards** covering
the whole Expo-managed surface, so any current *or future* SDK-pinned package is
ignored without another config change. Dependabot still flags security
advisories, still surfaces a new SDK via the `expo` major tripwire (FTY-125,
preserved), and still bumps genuinely independent deps (e.g. `typescript`). The
result: routine doomed mobile PRs stop for good; the SDK-governed set advances
only via the coordinated `expo install --fix` upgrade (the roadmap backlog note).

## Scope

- **Add prefix-wildcard `ignore` entries** to the `/mobile` `npm` block so the
  Expo-managed surface is covered (all update types — these realign via
  `expo install`, not in isolation):
  - `expo-*` — all Expo modules (`expo-camera`, `expo-router`, `expo-notifications`, …).
  - `@expo/*` — Expo scoped packages.
  - `@react-native/*` — the React Native toolchain (`@react-native/jest-preset`,
    `@react-native/babel-preset`, etc.); this is the exact gap that broke #83.
  - `react-native-*` — Expo-pinned community libs (`react-native-safe-area-context`,
    `react-native-screens`, `react-native-web`).
  - `@types/react*` — React type packages, pinned to the React version.
  - `eslint-config-expo` — Expo's SDK-tied eslint config.
- **Preserve the existing rules:** the FTY-125 `expo` entry (ignore patch/minor,
  major surfaces as the tripwire) is **unchanged**; the exact `react`, `react-dom`,
  `react-native`, `react-test-renderer`, `jest`, `jest-expo`, `@types/jest`
  ignores and the eslint-toolchain major rules remain.
- **Do NOT ignore `typescript`** (or other genuinely SDK-independent deps) — they
  should keep flowing through Dependabot.
- **Update the block comment** to explain the wildcard policy: the Expo-managed
  surface is governed by `expo install`; only the root `expo` major bump is a
  meaningful signal.

## Non-Goals

- **No SDK upgrade, no dependency bumps, no lockfile edits** — config-only.
- **No change to the `expo` tripwire** (FTY-125) or to other ecosystems
  (`github-actions`, `uv`, `docker`), nor to the `npm` entry's `schedule` /
  `open-pull-requests-limit` / `groups`.
- **No blanket disable of the mobile npm ecosystem** — Dependabot must still cover
  independent deps and security advisories; this targets only the Expo-managed
  surface.

## Contracts

- None. Only `.github/dependabot.yml` changes; `mobile/package.json` is read-only
  context to confirm the wildcards match the actual Expo-managed packages.

## Security / Privacy

- **Net positive, config-only.** Security advisories for any package (including
  the ignored ones) still surface — Dependabot `ignore` suppresses version-update
  PRs, not security alerts. The SDK-governed set takes its upstream security fixes
  via the coordinated SDK upgrade. No secrets, tokens, or private automation enter
  the public repo; no runtime behaviour change.

## Acceptance Criteria

- `.github/dependabot.yml` is valid YAML and a schema-valid Dependabot v2 config.
- The `/mobile` `npm` `ignore` block adds the wildcards: `expo-*`, `@expo/*`,
  `@react-native/*`, `react-native-*`, `@types/react*`, and `eslint-config-expo`.
- The FTY-125 `expo` patch/minor tripwire entry and all prior exact/eslint ignores
  are unchanged.
- `typescript` is NOT ignored.
- Each wildcard matches at least one real package in `mobile/package.json` (or is a
  forward-looking Expo-scope prefix), and the block comment explains the policy.
- No dependency versions, app code, workflows, or lockfiles are modified; root
  `make verify` stays green.

## Verification

- **YAML + schema:** the file parses as YAML and conforms to the Dependabot v2
  schema (local parse + shape; GitHub validates authoritatively post-push).
- **Coverage check:** assert each wildcard matches the intended packages in
  `mobile/package.json` (`@react-native/jest-preset`, `expo-*`, `react-native-*`,
  `@types/react*`, `eslint-config-expo`) and that `typescript` is still
  un-ignored and the `expo` tripwire entry is intact.
- **Regression:** root `make verify` passes (config-only).

## Planning Notes

- **Why wildcards over enumeration.** Expo's compatibility matrix pins the whole
  managed surface; new pinned packages appear across SDK releases. A per-package
  list is guaranteed to leak (it already did, 5 times). Scope/prefix wildcards
  (`expo-*`, `@react-native/*`, `react-native-*`, `@expo/*`, `@types/react*`) are
  stable against that churn.
- **`ignore` suppresses version PRs, not security alerts** — so breadth here does
  not blind us to CVEs; Dependabot security updates still open.
- **Glob support:** Dependabot `dependency-name` accepts `*` globs; if the current
  resolver rejects a specific pattern, fall back to enumerating the concrete
  packages present and note the gap.
- No evidence research warranted — supply-chain hygiene config.

## Readiness Sanity Pass

- **Product decision gaps:** none. The breadth question was decided (broad Expo
  wildcards). `ready`.
- **Sizing:** one boundary — **governance** config only. Zero big rocks. One story.
  Serializes on the governance lane after FTY-125 (same file), which is already
  merged.
- **Cross-lane impact:** none beyond governance.
- **Security/privacy risk:** low — config-only; security alerts preserved.
- **Verification path:** YAML/schema parse + wildcard coverage assertion + `make verify`.
- **Assumptions safe for autonomy:** yes — a bounded config edit with CI as the gate.

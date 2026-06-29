---
id: FTY-128
state: ready
primary_lane: governance
touched_lanes: []
review_focus:
  - changelog-covers-all-merged-work
  - grouped-by-milestone-theme
  - merged-features-only-no-unshipped
  - no-version-source-change
  - public-repo-boundary
risk: low
tags:
  - docs
  - changelog
  - release
approved_dependencies: []
requires_context:
  - docs/architecture/system-overview.md
  - docs/contracts/README.md
  - docs/standards/coding-standards.md
autonomous: true
---

# FTY-128: Bring `CHANGELOG.md` Current For The v1.0.0 Cut

## State

ready

## Lane

governance

## Dependencies

- None to schedule. Every feature this story records is **already merged**;
  this is a docs-only reconciliation. It authors in parallel with FTY-129
  (`target-calculator.md`), FTY-130 (`threat-model.md`), and FTY-142
  (`README.md` / `contracts/README.md` / `system-overview.md`) — **no file
  overlap**: this story owns **`CHANGELOG.md` and nothing else**.

## Outcome

`CHANGELOG.md`'s `v1.0.0` section reflects the **whole** shipped v1 surface, not
just the feature set that existed when it was last written. An "accurate
CHANGELOG" is part of the release-ready definition (the same bar FTY-080 set),
and today the file stops at the provider-access work (FTY-087/088/089) and omits
a large tranche of merged work after it. After this story a reader of the public
repo sees every shipped capability grouped by theme.

The currently-missing merged work, by theme (the author confirms the exact set
and IDs from `git log` on `main` plus the merged story roadmap before writing —
treat this list as the floor, not the ceiling):

1. **Ops / deploy hardening** — Compose network hardening with Postgres/Redis no
   longer published to the host + worker healthcheck + restart policies
   (FTY-109); baseline security response headers + interactive-docs gating in
   production (FTY-112); non-root backend container (FTY-116); the `/readyz`
   DB-readiness probe (FTY-117); per-IP / per-account auth-endpoint rate limiting
   (FTY-118); the Dependabot expansion to app + Docker ecosystems and the
   Expo-SDK ignore/tripwire tuning (FTY-108/121/125/126).
2. **New / extended read & goal endpoints** — the goals + target-reveal route
   that turns a direction + pace preset into a persisted goal and a revealed
   target with provenance (FTY-106); the daily-summary **range** read endpoint
   and its mobile Trends consumer (FTY-123/124); the manual target override +
   reset surface and macro targets surfaced through the read-model
   (FTY-094/095/105) where not already recorded.
3. **Estimator robustness** — evidence clients fail closed on malformed
   FDC/OFF payloads (FTY-110); LLM rate-limit retry with backoff (FTY-113);
   LLM provider output hardening / size caps (FTY-114); the nutrition
   plausibility bound (FTY-115); per-item provenance + portion adjust and item
   re-match (FTY-092/093).
4. **Backend correctness / fail-closed** — explicit-null and registration-race
   fail-closed at the input boundary (FTY-111); the weight-entry future/absurd
   date bound (FTY-119); the day-window + active-target helper consolidation
   (FTY-120, an internal refactor — record only if the changelog tracks
   internal-quality changes; otherwise omit).
5. **The Milestone 10 UX redesign** — the mobile design system (FTY-097) and the
   redesigned Today, Log, correction sheet, Trends + weigh-ins, Profile/Settings,
   and offline-queue logging screens (FTY-098/099/100/101/102/104), plus the
   self-host sign-in / connection flow (session token store FTY-090, connect-to-
   server FTY-107, sign-in/create-account FTY-091).

## Scope

- **Edit only `CHANGELOG.md`.** Extend the existing `v1.0.0 — 2026-06-28`
  section so it covers the merged work above. Keep the existing entries; add the
  missing ones.
- **Group by milestone / theme**, matching the file's current sectioning style
  (`### Accounts & Profile`, `### Logging Spine`, …). Add or extend sections as
  the new work warrants — natural homes are an expanded
  **Infrastructure & Self-Hosting** / **Security** for the hardening tranche, the
  existing **Weight & Daily Summary** / a **Goals & Targets** section for the new
  endpoints, an **Estimator & Evidence Sources** extension for the robustness
  work, and a new **Mobile UX (v1 Redesign)** section for Milestone 10.
- **Derive entries from the merged feature set**, not from this spec. The author
  uses `git log` on `main` and the merged stories to confirm what actually
  shipped, and writes each entry as a user-facing capability line with its FTY
  id(s) in parentheses — the established style of every existing entry.
- **Merged work only.** A story that is `ready` / `ready_with_notes` /
  `candidate` but not merged (e.g. FTY-103 onboarding redesign at time of
  writing) is **not** a shipped feature and must not be listed. The author
  verifies merge status before including any line.

## Non-Goals

- **No version-source change.** Do not touch `backend/pyproject.toml`,
  `mobile/package.json`, or `mobile/app.json`, and do not change the
  `## Version Sources` table or the `1.0.0` strings — the version is already
  cut; this is a content reconciliation, not a version bump.
- No product code, schema, endpoint, contract, or behaviour change.
- No new top-level version section — this is still the `v1.0.0` cut; the missing
  work shipped under v1, so it belongs in the existing `v1.0.0` section.
- Do not document private automation, runner internals, machine paths, tokens,
  or queue state — `CHANGELOG.md` is in the **public** repo (see the
  public-repo boundary).

## Contracts

- **None.** This records already-shipped behaviour; no request/response shape,
  schema, or contract changes. `docs/contracts/README.md` is referenced only to
  cross-check which capabilities have a contract worth naming in a line.

## Security / Privacy

- Docs-only, **public repo**. The single risk is leaking private automation
  detail or unshipped/internal-only context into the public changelog; the
  author records **product** capabilities only and honours the public-repo
  boundary (no runner code, paths, tokens, or queue state). Rated **low**.

## Acceptance Criteria

- `CHANGELOG.md`'s `v1.0.0` section covers the merged hardening tranche, the new
  goal/target-reveal and daily-summary-range endpoints, the estimator-robustness
  work, the backend fail-closed fixes, and the entire Milestone 10 UX redesign —
  each as a themed, user-facing line with its FTY id(s).
- Every added line corresponds to **merged** work on `main`; no `ready` /
  `candidate` (unshipped) story is listed.
- Entries are grouped by milestone / theme consistent with the file's existing
  sectioning style.
- **No version string, `## Version Sources` table, or `1.0.0` value is added or
  changed**, and no version-source file is touched.
- Nothing private (runner code, machine paths, tokens, queue state) appears.
- `make verify` passes (governance boundary + any docs/link checks).

## Verification

- `make verify` (governance boundary + docs checks); the public-repo boundary
  check stays green.
- Manual diff cross-checking the added entries against `git log` on `main` and
  the merged story set — confirming each line is real, merged, and correctly
  attributed, and that no version content changed.

## Planning Notes

- **One judgment call — section taxonomy.** Whether the Milestone 10 work is one
  `### Mobile UX (v1 Redesign)` section or folded into the existing mobile-facing
  sections is the author's discretion; either is fine if every merged item is
  present and grouped coherently. No product decision is pending.
- **No evidence research warranted** — this records what shipped; it settles no
  health/nutrition/behavioural question.
- **Source of truth for the feature list** is the merged code/stories, not this
  spec — the spec's list is a floor to prevent omissions, deliberately leaving
  the author to confirm IDs and exact wording from `git log`.

## Readiness Sanity Pass

- **Product decision gaps:** none — every line documents already-merged
  behaviour; wording and section grouping are author discretion.
- **Cross-lane impact:** governance (docs) only, **no touched lanes**. **Single
  boundary, zero big rocks:** no contract change, no migration/new table, no new
  trust boundary. Owns `CHANGELOG.md` exclusively — no overlap with FTY-129/130/142.
- **Size:** `review_focus` = 5 (at the ceiling), `requires_context` = 3 (under
  8). One story.
- **Security/privacy risk:** low — public-repo docs; the only hazard is leaking
  private automation, explicitly fenced off.
- **Verification path:** `make verify` + a `git log`-cross-checked read-through
  diff.
- **Assumptions safe for autonomy:** yes — the themes and the missing-work floor
  are enumerated, the merged-only rule is explicit, and the file is owned solely
  by this story.

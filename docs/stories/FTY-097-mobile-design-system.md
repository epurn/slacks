---
id: FTY-097
state: ready_with_notes
primary_lane: mobile-core
touched_lanes: []
risk: medium
tags:
  - mobile
  - design-system
  - tokens
  - theming
  - typography
  - tab-shell
approved_dependencies: []
requires_context:
  - docs/design/ux-design.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/repo-layout.md
review_focus:
  - accessibility
  - theming-correctness
  - typography-and-font-integration
  - motion-and-haptics
  - navigation-shell-migration
autonomous: true
---

# FTY-097: Mobile Design System — Tokens, Theming, Primitives, Tab Shell

## State

ready_with_notes

## Lane

mobile-core

## Dependencies

- None. This is the visual foundation. Every subsequent screen-rebuild story
  (Today, Log, Trends, Profile, onboarding, sign-in, correction sheet) **depends
  on this** and consumes its tokens, primitives, and shell. It must land first.

## Outcome

The mobile app gains a single reusable design foundation that every screen sits
on, replacing today's ad-hoc inline `StyleSheet.create` hex values and the
single hardcoded-`Stack` shell. After this story:

1. There is **one source of truth for design tokens** (color, spacing, radius,
   typography, motion) with **light and dark themes**, resolved against the
   system color scheme. Components read tokens through a theme accessor, not
   literal hex.
2. The **display typeface is integrated behind a single font token** and renders
   hero numerals/headers with **tabular figures** (fixed-width digits that do not
   jitter as live numbers update).
3. A small set of **shared primitives** exists — themed text/number, card,
   skeleton/shimmer placeholder, button, the source/provenance icon set, plus
   haptic and spring helpers — so screen stories assemble UI from them instead of
   re-deriving styling.
4. The app shell is the **standard native three-tab bar (Today · Log · Trends)**
   with the **gear-in-header** Profile/Settings affordance, an `.ultraThin` tab
   bar material, and the existing Today screen wired into the Today tab.

This is the "native skeleton, bespoke soul" foundation from the design doc §5:
native chrome and behaviour, with the product's identity carried by type, the
amber/honey accent, and restrained motion.

## Scope

Per `docs/design/ux-design.md` §5 (Visual & tone) and §7 (Cross-cutting):

**Tokens & theming**
- Define a **token module** for color, spacing, radius, and elevation as the
  single source of truth (e.g. `mobile/theme/`), with **light and dark palettes**:
  minimal monochrome canvas + one **warm amber/honey accent**; dark = elevated
  charcoal (≈`#1C1C1E` base, ≈`#2C2C2E` raised cards, near-white text) — a
  bespoke-tuned dark surface, **not** pure-OLED black and **not** a mechanical
  inversion. Include the over-budget **coral** over-segment color (§6) as a token
  so the hero bar story can consume it.
- Provide a **theme accessor** (hook/context) that resolves the active palette
  from the system color scheme via `useColorScheme`. Expose a seam for an explicit
  Light/Dark/System override, but **do not** build the settings UI for it (that is
  the Profile story). Default behaviour follows the system.
- Tokens must satisfy **WCAG AA** contrast in both themes (text-on-surface,
  accent-on-surface, the muted/de-emphasized tones used for "needs a detail").

**Typography & the display face**
- Integrate the bundled font assets and expose **typography tokens**: SF Pro
  (system) for body that honours **Dynamic Type**, and the **modern geometric
  grotesque display face** for hero numerals and headers, with **tabular figures**
  enabled and tight header tracking.
- Provide a themed **number/figure primitive** that uses the display face with
  tabular numerals so a live-updating number (the hero total) does not change
  width as digits change.
- Put the display face behind **one font token** so the final licensed face can
  swap in a single place (see Notes — the exact face is an open sourcing decision).

**Primitives**
- Themed **Text** and **Number/Figure** components (read typography + color
  tokens; respect Dynamic Type within sane bounds for the display hero).
- A **Card** surface (flat opaque timeline card per §5 — not glass).
- A **Skeleton/Shimmer** placeholder used for the in-place "thinking" / loading
  state (§3, §6: resolve in place, no layout shift); shimmer **degrades to a
  static placeholder under Reduce Motion**.
- A themed **Button** primitive (primary/secondary) with ≥44pt tap target and
  the accent treatment.
- The **source / provenance icon set** as a reusable component keyed by source
  (NL/USDA-search, barcode, label-scan, edited, saved-food, rough-estimate,
  offline-pending), each with a built-in VoiceOver label. This supersedes the
  existing ad-hoc `StatusIcon`/glyph usage; migrate current call sites to it.
- **Haptic helpers** (e.g. light/success/selection) and a **spring config**
  helper for the restrained default motion, both **honoring Reduce Motion** (no
  haptic spam; signature beats degrade to simple fades). Introduce the motion/
  haptic dependencies (e.g. `expo-haptics`, and a reanimated/Animated-based
  spring) per the FTY-013 dependency rule — declare any added dependency in the
  PR with justification and update this story's metadata first.

**Tab shell**
- Replace the single `Stack` root (`app/_layout.tsx`) with the **standard native
  three-tab bar**: Today · Log · Trends, three equal SF-Symbol tabs, **no raised
  center button**, `.ultraThin` tab-bar material. Wire the **existing Today
  screen** into the Today tab unchanged in behaviour.
- Provide **Log** and **Trends** tab routes as minimal placeholders that the
  respective screen stories fill in — the shell must host them without those
  stories existing yet, and must not regress current Today behaviour, profile, or
  weight routes.
- Add the **gear-in-header** Profile/Settings affordance pattern available on each
  tab (the header surface + the gear control that routes to the existing profile
  route); the full Profile redesign is a separate story.
- Drive `StatusBar` style from the active theme (replacing the hardcoded
  `style="dark"`) so the status bar is correct in both light and dark.

## Non-Goals

- **Any specific screen's content or layout.** Today/Log/Trends/Profile/
  onboarding/sign-in/correction-sheet are separate stories that **consume** these
  tokens and primitives. This story only sets up the foundation and a placeholder
  Log/Trends tab.
- The **Light/Dark/System override UI** in Settings (Profile story) — only the
  token/accessor seam is built here.
- **Purchasing/licensing the final display font.** Implement against a
  bundle-able geometric grotesque with tabular figures as an interim, behind the
  single font token (see Notes).
- The hero progress bar, over-budget rendering, correction sheet, charts, and any
  other screen component — those consume the coral/amber/skeleton tokens defined
  here but are built in their own stories.
- Any backend, contract, schema, or API change.

## Contracts

- **None.** This is client-only styling and navigation structure. No server
  contract, DTO, schema, or job boundary is touched. It introduces an internal
  mobile theming convention (the token module + theme accessor + primitives) that
  later mobile stories build on, but no cross-package contract.

## Security / Privacy

- **None.** Client styling, theming, fonts, and navigation only. No user data is
  read, stored, transmitted, or logged by this work; the provenance icon set
  renders source *labels*, never values. No new trust boundary, no untrusted
  input, no secrets. Bundled font assets must be license-clean and committed only
  if redistribution is permitted (see Notes).

## Acceptance Criteria

- A single token module is the source of truth for color, spacing, radius, and
  typography; components read tokens via the theme accessor rather than literal
  hex. The legacy inline hex in migrated components is replaced by token reads.
- Light **and** dark themes both render: switching the simulator/system
  appearance flips the whole shell and migrated primitives (charcoal dark base,
  near-white text, amber accent that glows rather than blares) with no broken or
  unreadable surfaces. Token contrast meets **WCAG AA** in both themes.
- The display face renders hero numerals/headers with **tabular figures**: a
  changing multi-digit number keeps constant width (no horizontal jitter). The
  face is referenced through one font token.
- The shell is a **three-tab native tab bar** (Today · Log · Trends) with an
  `.ultraThin` material and a gear-in-header Profile affordance; the existing
  Today screen works inside the Today tab and the profile/weight routes still
  resolve. No raised center button.
- Skeleton/shimmer, button, card, themed text/number, and the provenance icon set
  exist as reusable primitives; current ad-hoc status-glyph usage is migrated to
  the provenance icon component.
- **Accessibility:** Dynamic Type scales body text (and the display hero within
  bounds); every provenance icon and tab carries a VoiceOver label; all tap
  targets are ≥44pt; **Reduce Motion** degrades shimmer and signature beats to
  static/simple fades; color is never the sole signal.
- TypeScript strict passes; mobile lint and tests pass via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile):
  - Unit tests for the theme accessor: correct palette resolves for light vs dark
    system scheme, and the override seam picks the forced palette.
  - A token contrast assertion (text/accent/muted on each surface meets the AA
    ratio) for both themes.
  - Component tests for each primitive: themed text/number renders with tabular
    numerals, skeleton renders and collapses to static under a mocked Reduce
    Motion signal, button enforces the ≥44pt target and disabled state, the
    provenance icon set renders the correct icon + VoiceOver label per source.
  - Tab-shell test: three tabs present (Today · Log · Trends), Today tab renders
    the existing Today screen, gear affordance routes to profile, no center
    button.
  - Accessibility checks: VoiceOver labels on tabs and provenance icons; tap-target
    sizes.
- Run mobile typecheck, lint, and tests via `make verify` (the `mobile/verify.sh`
  hook: `npm ci` → `npm run typecheck` → `npm run lint` → `npm test`).
- On an iOS simulator, confirm the **same screen renders correctly in light AND
  dark** (toggle system appearance) and the tabs/gear navigate.

## Planning Notes

- This formalizes the styling that is currently scattered as inline
  `StyleSheet.create` hex across `components/` (e.g. `TodayScreen.tsx`,
  `DailySummary.tsx`) and replaces the hardcoded-`dark` `app/_layout.tsx` Stack.
  Migrating every existing screen to tokens is **not** required here — migrate
  the shell, the components touched to host the tabs, and the status-glyph →
  provenance-icon swap; remaining screens migrate as they are rebuilt in their
  own stories.
- The design doc's named principles to honor: **"Native skeleton, bespoke soul"**
  (native chrome; identity via type/accent/motion) and **"Expressive carriers"**
  (only a few elements carry the brand — the hero numeral face, the amber accent,
  the signature motion beats). Keep ~95% calm.
- Any added dependency (haptics, animation/spring, font loader) follows the
  FTY-013 dependency rule: declare it in the PR with justification and update this
  story's `approved_dependencies` first.

## Readiness Sanity Pass

- **Product decision gaps:** none blocking. The visual direction (monochrome +
  amber accent, elevated-charcoal dark, geometric-grotesque display with tabular
  figures, three native tabs, gear-in-header, restrained materials/motion) is
  fully resolved in `docs/design/ux-design.md` §5/§7. The one open item — the
  **exact licensed display face** — is deliberately decoupled: build against a
  bundle-able geometric grotesque with tabular figures behind a single font token
  so the final face swaps in one place. Captured as `ready_with_notes`.
- **Evidence basis:** no new research warranted. This is pure client styling; the
  only evidence-backed decision the design turns on (weigh-in cadence) is already
  cited in §4b and belongs to the Trends/Profile stories, not this foundation.
- **Cross-lane impact:** none. Single boundary — **mobile-core** only. No
  contract change, no schema migration, no new untrusted-input trust boundary; no
  big rocks. Docs ride along (non-serializing). No split required on boundary
  grounds.
- **Sizing call:** sits **at the `review_focus` ceiling (5 concerns)** and well
  under the `requires_context` ceiling (4 docs), so it does **not** breach two
  limits — it stays one story. The five concerns are tightly coupled (tokens,
  typography, motion, primitives, and the shell are one interdependent foundation
  every screen consumes, with no clean contract to split them across). A split is
  *available* if scope grows during implementation — the natural seam is
  **type/font + motion/haptics** vs **color-tokens/theming + tab-shell** as two
  dependent stories — and should be taken rather than overrunning the author's
  turn budget. Recorded here per the ceiling rule.
- **Security/privacy risk:** none. Client-only; no data, no secrets, no trust
  boundary. Bundled font assets must be license-clean.
- **Verification path:** mobile unit/component tests (theme accessor, AA contrast,
  each primitive, tab shell, Reduce-Motion degradation, a11y labels) plus
  `make verify` and a light/dark + navigation simulator smoke check.
- **Assumptions safe for autonomy:** yes. No dependency on unmerged stories (this
  is the foundation). Interim font + any added haptic/animation dependency are
  declared per the FTY-013 dependency rule; the final licensed face swaps behind
  the single font token without touching consumers.

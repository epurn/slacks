# Slacks — UX Design

The canonical description of what the Slacks product *is*: its frame, information
architecture, core flows, screens, interaction model, visual direction, states,
and cross-cutting stance. UX work should implement a slice of this doc rather than
re-deciding the design; the living taste that governs it — Slacks' design
philosophy — is maintained alongside the agent tooling, embedded into agent work,
and enforced in review. This doc must stay consistent with it.

> Status: v1 design, resolved whole-product. Two sourcing details remain open and
> are noted inline (the exact licensed display font; final chart range options).

---

## 1. Product frame

Slacks is an **iOS-native, self-hostable, natural-language calorie & macro
tracker**. The wedge is two things competitors don't do well together:

1. **Fast input** — describe what you ate in plain language ("a bowl of oatmeal
   with blueberries and a coffee"); also barcode and nutrition-label capture.
2. **Trust** — every number shows where it came from and is correctable. No opaque
   guesses.

**Core loop:** log → see your standing vs. target → correct if needed → move on.

- **v1 scope:** calories + macros. Weight is secondary (an outcome view, not the
  daily focus). Exercise is shown separately, never folded into the food math.
- **Center of gravity is STATUS-FIRST.** The home screen leads with the day's
  standing; logging is an action launched from it.

---

## 2. Information architecture & navigation

- **Floating glass switcher — two destinations: Today · Trends.** A persistent
  bottom-left segmented glass pill (see Visual), inspired by the iOS 26 Photos
  chrome, replaces the old full-width bottom tab bar (FTY-242) so the app presents
  as a modern full-screen shell rather than a conventional tab app. The routes are
  unchanged. **Today is the single logging surface and the dashboard** — there is
  no separate Log destination (consolidated in FTY-147; a separate surface
  duplicated the composer and drifted, and added a navigation hop to the core loop
  for no benefit).
- **Profile / Settings is a persistent gear** in the header on every screen — not a
  tab.
- Logging is always one tap away: the **composer sits directly beneath the Today
  hero** (status leads — see §1; order set in FTY-178), so capture happens on the
  status-home itself without a navigation hop.

---

## 3. Core flows

### Logging loop

- **Today's composer — directly beneath the hero — is a natural-language
  composer.** You describe the food; a saved-food typeahead surfaces reactively
  as you type. Barcode and label
  capture sit alongside as SF Symbol affordances. (No proactive "recents" list in
  v1.) The composer does **not** auto-raise the keyboard — Today is the
  status-home; tapping the composer raises it (auto-focusing a dashboard is
  jarring; *Calm by default*).
- **Post-submit, you stay on Today** — no automatic navigation (page changes are
  jarring). The submitted entry appears immediately in **Today's one canonical
  timeline** as a present, pending row and the field clears for the next one,
  enabling rapid successive adds.
- **The "thinking" state is a skeleton/shimmer that fills in place;** resolved
  values fade in exactly where the placeholder was. No layout shift.
- **Today owns the single canonical timeline.** There is no separate "added this
  session" feed — the optimistic insert *is* the acknowledgement.
- **Correction is a universal slide-up sheet** from any item (see §4a) — never a
  page change.
- **Deletion is the standard iOS swipe-left-to-delete** on any server-backed
  timeline row (a resolved item or a raw needs-a-detail / failed entry): a left
  swipe reveals a single destructive **Delete** action, and tapping it soft-voids
  the entry (the swipe reveal is the confirmation — no extra alert, per native
  convention; there is no undo in v1). The row leaves the timeline immediately
  (optimistic) and the day totals update in place; a failed delete restores the
  row with a calm inline error, never a silent loss. VoiceOver users reach the
  same action as a "Delete" custom action on the row. Tap still opens the
  correction sheet — deletion never fights the tap.
- **Missing details are asked inline, non-blocking.** When Slacks needs a detail to
  be accurate, the entry shows a gentle "needs a detail" affordance and is *not
  counted* in totals until answered. Slacks never fabricates a number.

### Barcode & label capture

The camera is a full-screen cover the user deliberately invokes from Today's
composer (an intended modal, not a surprise navigation), dismissing back to Today.

- **Barcode = fast-add (high trust).** A successful scan resolves the product and
  lands it directly in the feed/timeline like any entry (barcode provenance),
  correctable afterward. Barcode not found → fall back to the NL composer
  (pre-filled), never a dead end.
- **Label = capture-then-confirm (OCR is fallible).** Capture the nutrition label,
  then confirm the parsed values (looks-right / edit) before it's added (label
  provenance). Unreadable scan → retake or type. This keeps OCR misreads out of the
  day's totals — Slacks never silently trusts a fallible parse.

### Onboarding

A goal-led 3-step flow: **goal + pace → measurements → target reveal → Today.**
Units and timezone auto-detect; the metabolic formula provides sensible defaults.
This captures the goal the target calculation needs. Returning users (persisted
session) skip straight to Today.

---

## 4. Today screen

The status-first home.

- **Hero: calories consumed vs. target only** — a bold number plus a slim linear
  bar ("1,240 / 2,000 kcal · 62%"). One focus. The hero leads the screen
  (status-first), with the composer directly beneath it (§3; FTY-178).
- **Secondary tier (below the composer):** compact macro chips (P/C/F) that read
  consumed-vs-target ("P 80/155g", sourced from the daily-summary target
  read-model; consumed-only when no target is set), then a distinct exercise burn
  line with an icon-system flame glyph (SF Symbol, never an emoji). Exercise is
  **not** in the hero and **not** a fourth macro, and its figure is never folded
  into the food/calorie math.
- **Timeline:** items-forward, grouped into **time clusters** (entries within a
  ~10–15 minute grace window combine, text-message-chain style). Each item shows
  name · kcal · an **always-on source icon**. The raw phrase appears only on tap
  (the item sheet).
- **Empty state — full budget + gentle invite.** Before anything is logged the hero
  shows the full target as available ("0 / 2,000 kcal · 2,000 to go") in a calm,
  neutral tone — never an alarming empty zero; the bar is an empty track. The
  timeline shows one soft invite ("Log your first thing") anchored to the composer.
  Oriented, not blank, not a coachy illustration.
- **Corrected values** simply carry the "✎ edited" source icon in the timeline (no
  special-case treatment — it's just another provenance); the item sheet can note
  the original→corrected change.
- **"Needs a detail" entries** sit in the timeline muted/de-emphasized with a gentle
  inline tag, visibly uncounted until answered; tapping opens the sheet in
  clarify-mode (§4a).

### 4a. Detail / correction sheet

The universal slide-up sheet from any timeline item — the heart of the
trust-and-correct wedge.

- **Primary lever: portion / quantity-first.** The sheet leads with an amount
  stepper ("1 cup" → "1.5 cups"); kcal + macros recompute live from the source's
  per-unit data, so provenance stays intact (fixing the amount does **not** turn the
  item into a manual override). This matches how people actually mis-estimate.
- **Wrong-match correction: a "Change match" affordance.** Separate from the amount
  stepper. It reveals alternative source matches inline plus a search fallback;
  picking a new food re-aims the entry and recomputes from the new source
  (provenance updates honestly). So a misheard "turkey" → "chicken" is fixed without
  delete-and-retype, and the entry keeps its place. (Direct value override remains
  an advanced third lever, which marks the item user-edited.)
- **Evidence / provenance block: source line + your words + an estimate nudge.**
  Every sheet shows the source label & icon and matched entry name (e.g. "🔍 USDA ·
  Turkey breast, roasted", "📷 Label scan", "✎ You edited"), plus the user's original
  phrase quoted. A rough estimate is treated distinctly ("≈ Rough estimate" + an
  explicit "Make it exact" nudge). "Make it exact" is its own lever, distinct from
  Change match: Change match fixes a *wrong* source by search, while Make it exact
  asks the user for *product evidence* — a barcode or a nutrition-label photo — and,
  after a preview the user confirms, applies the resulting source (or a plainly
  labelled lower-trust fallback) to the item in place (FTY-306,
  `docs/contracts/evidence-retrieval.md`). Compact and calm — honest about
  origin, and it actively lifts the lowest-trust items rather than hiding them.
- **Clarify-mode (for "needs a detail"): Slacks' question + quick-pick chips +
  free-text fallback.** The specific question ("What milk?") with likely answers as
  tappable chips plus "type your own". One tap resolves → the entry recomputes and
  starts counting. Slacks never fabricates the missing detail.
- **Save-as-food: a manual action in the sheet.** Saves the current (corrected) item
  with its per-unit definition so it surfaces in the Log typeahead later. No
  auto-prompt or nagging. (Smart "save this for next time?" suggestions are v2.)
- **Detents: medium by default → large on demand.** Opens at a medium detent showing
  the common case (header + amount + evidence + primary actions); grows to large only
  when Change-match search or the override fields open. The timeline stays partly
  visible behind for the quick fix.

### 4b. Trends screen

Where time-over-time lives.

- **Hierarchy: weight outcome up top, intake behavior below.** Lead with a smoothed
  weight-trend line drawn over the noisy daily weigh-in points, with a range selector
  and the headline delta ("182.4 lb · ↓1.8 this month"). Beneath it, an
  intake-adherence summary over the same range (avg kcal vs. target, days-on-target,
  a compact adherence strip). Weight is the outcome users open Trends to check;
  intake sits right beneath as the "why". One screen keeps the outcome↔behavior link
  intact.
- **Past-day drilldown:** tapping a day in the intake history opens that day's
  timeline (the Today layout for that date).
- **Weight logging: from the Trends weight card.** A "+ log weight" opens a small
  numeric entry sheet (defaults to today, seeded with the last value). Weight logging
  is deliberately **not** on the status-first Today screen and not buried in Profile.
- **Weigh-in cadence: default weekly, user-adjustable** (Weekly · Every 2 weeks ·
  Monthly · Off). Slacks must **not** encourage scale-watching: the reminder is
  low-frequency and fires only when a reading is actually due — never daily, no
  streaks — and the UI leads with the smoothed trend, de-emphasizing any single day's
  number. This is evidence-based: weekly weighing captures the full weight-loss
  benefit (daily confers no added benefit in RCTs), ~4 readings/month is plenty for a
  meaningful trend, and the psychological harm of self-weighing is daily-specific and
  concentrated in at-risk groups. See the *Encourage the trend, not the scale*
  principle.

  *Open: exact range options; macro-history depth.*

### 4c. Profile / Settings

A **control panel for your numbers**, not a generic settings dump. Opens from the
header gear as a native grouped settings screen, but it leads with the numbers the
whole app depends on:

- **YOU:** Goal (lose/maintain/gain + pace), Calorie target (with visible
  provenance), macro targets.
- **BODY:** weight, height, age, sex, activity level (the metabolic-formula inputs).
- **PREFERENCES:** units, weigh-in reminders, notifications, appearance.
- **ACCOUNT & SERVER:** sign-in/session, self-host server connection, sign out.
- **DATA & ABOUT:** export/delete, about/version.

It mirrors the inputs onboarding captures, so this is where you edit them later.

- **Calorie target: derived by default, with a clearly-marked manual override.**
  Computed from goal + pace + body metrics via the metabolic formula and shown *with*
  its provenance ("└ from your goal + metrics"). Editing goal/pace/metrics recomputes
  it with a mini target-reveal. A manual override is marked "✎ set by you" with a
  reset to the derived value. The "every number shows where it came from" principle
  applies to the target itself.
- **Macro targets: auto-derived from the target + goal, with a marked override.**
  Sensible defaults (protein anchored to bodyweight, the rest split), shown with
  provenance; overridable and then marked, with reset. This is what the Today P/C/F
  chips measure against.
- **Units / appearance / notifications (conventional):** units auto-detect from
  locale, overridable (metric/imperial; kg/lb; kcal). Appearance follows system with
  an explicit Light/Dark/System override. Notifications are minimal and calm — opt-in,
  no daily-logging nag and no streaks; the only standing nudge is the occasional
  weigh-in reminder (see §4b).

### 4d. Sign-in & self-host connection

- **Self-host-first, with accounts on your own server.** First run: (1) connect to
  your Slacks server — enter or scan the server URL; (2) sign in or create an account
  on that server (email + password); (3) → onboarding → Today. The session persists,
  so returning users skip to Today. Accounts live on the user's own server. The LLM
  provider's authentication is a server-side setup concern, separate from this
  user-facing sign-in.
- **Setup QR carries the server URL only** (no embedded secret) — scanning connects
  the app; the user still creates the account manually. A simpler, safer QR; manual
  URL entry is the fallback.

  *Connect / sign-in / create-account screen detail and their error states are
  covered under States & edges (§6).*

---

## 5. Visual & tone

**North star: iOS-native, ultra-modern, premium, calm — not a generic calorie app.**
The balance is *native skeleton, bespoke soul* — native in structure and behaviour,
unmistakable in a few expressive carriers (see the principle of that name).

- **Navigation: a bottom-left floating glass switcher** (Today · Trends) — a
  compact segmented pill of translucent blur material with SF-Symbol segments and
  a clear selected state, floating over a full-screen shell (FTY-242, replacing the
  old full-width tab bar). Native materials and safe-area/accessibility rules, not
  decorative custom chrome; no raised center button. (Logging lives on Today, not a
  separate destination — FTY-147.)
- **Aesthetic: minimal monochrome + one accent** — neutral canvas, airy whitespace,
  crisp bold type, a single accent for actions, emphasis, and progress.
- **Accent: warm amber / honey.** Distinctive and premium-calm — deliberately not the
  generic health-app green nor iOS system blue. The hero bar fills amber toward the
  target ("on track").
- **Light/dark: both, system-following; dark = elevated charcoal.** iOS-native
  layered greys (≈#1C1C1E base, ~#2C2C2E raised cards), near-white text — soft and
  premium; the amber glows rather than blares. Not pure OLED black. Dark is a
  first-class, bespoke-tuned surface, not a mechanical inversion.
- **Typography: a bespoke display face for hero numerals + headers, SF Pro for
  body.** The display face is a **modern geometric grotesque** — clean, confident,
  subtly warm, with **wide tabular numerals** (the hero number updates live and must
  not jitter width) and tight header tracking. SF Pro body keeps Dynamic Type and
  native feel. *Open: the exact licensed font (must have tabular figures, be
  bundle-able, and hold up at very large sizes).*
- **Materials & depth: restrained system materials.** iOS blur only where iOS
  naturally blurs — the floating switcher pill (system chrome material), correction
  sheets (frosted, content dims behind), large-title nav frosting on scroll.
  Timeline cards stay flat opaque. Layered and native, but calm — no "glass
  everywhere".
- **Motion & haptics: restrained by default + a few signature moments.** Quiet,
  physical default motion — short springs, in-place fades (skeleton → value), the hero
  bar easing as it fills; no layout shift. Identity lives in a small set of designed
  beats with matching haptics: an entry resolving (shimmer → value + soft tap), a
  correction saved, the target reached (gentle pulse + success haptic). Calm ~95% of
  the time, branded at the few beats that matter.

---

## 6. States & edges

- **Offline / server-unreachable logging: queue raw, resolve on reconnect.** You can
  still capture text offline; it stacks as a pending entry (uncounted, with an offline
  indicator) and auto-parses + counts once the server is reachable — reusing the
  pending pattern (capture the thought now, keep the number honest). A gentle
  connection banner shows status. Never blocks capture, never fabricates a number.
- **Over-budget hero: amber fills to target, coral over-segment past it.** The bar
  fills amber to 100% at the target line, then a distinct coral over-segment extends
  beyond it; the copy flips "X to go" → "X over". Both portions stay visible. Calm but
  unambiguous — and always paired with the "over" text (never color alone).
- **Other edges (principled defaults):** per-entry parse errors show a gentle inline
  "couldn't read that" with retry + edit-as-text (uncounted, never a crash, never a
  fabricated number); Trends empty shows a calm invite ("Log your first weigh-in");
  Log empty is just the composer; sign-in errors are clear and retryable, never a
  dead-end; loading is always a skeleton/shimmer in place.

---

## 7. Cross-cutting

- **Accessibility:** full Dynamic Type (SF Pro body scales; the display hero number
  scales within sane bounds); VoiceOver labels on every provenance icon and the hero
  ("1,240 of 2,000 kcal, 62%, 760 remaining"); never color as the sole signal;
  ≥44pt tap targets; respects Reduce Motion (signature beats degrade to simple fades);
  target WCAG AA contrast.
- **Device scope:** iPhone, all sizes (SE → Pro Max), portrait-first. No iPad- or
  landscape-specific design in v1.
- **Performance feel:** optimistic + in-place always; skeletons resolve in place with
  no layout shift; long timelines virtualized.
- **Privacy-visible:** data lives on the user's own server (self-host); the app is
  explicit about where data goes; provenance reinforces the transparency stance.

---

## v2 / parked

- A smart, context-aware food recommender on Today's composer (time-of-day /
  patterns, Spotify-style) that replaces a naive recents list.
- Smart "save this for next time?" suggestions in the correction sheet.

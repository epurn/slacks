# Fatty UX Design — WORK IN PROGRESS (paused 2026-06-28)

Whole-product, design-first session run via the `design` skill. Eventual home of
the finished doc: `fatty/docs/design/`. This command-centre file holds the
decisions while the design is incomplete. **Resume by re-reading this, then
continue the deep grill at the open items below.**

## 1. Product frame  [RESOLVED]
- iOS-first, self-hostable NL calorie/macro tracker. Wedge = (a) fast input
  (NL/barcode/label) + (b) trust (every number shows its source, correctable).
- Core loop: log → see standing vs target → correct → move on.
- v1: calories + macros only; weight secondary; exercise shown separately.
- **Center of gravity: STATUS-FIRST.** Home hero = the day's standing; logging is
  an action from it.

## 2. Information architecture & navigation  [RESOLVED]
- Bottom tabs: **Today · Log · Trends**. Log is its own dedicated full page.
- **Profile/Settings = persistent gear** in the header on every screen (not a tab).
- ⊕-emphasis on the Log tab was tentative → revisit in the visual layer (likely a
  standard iOS tab, not a big center button).

## 3. Core flows  [RESOLVED]
**Logging loop:**
- Log page (v1) = **keyboard-up NL composer**; describe it. Saved-food typeahead
  surfaces reactively as you type; barcode + label as SF Symbol affordances. No
  proactive recents in v1.
- **Post-submit: stay on the Log page** (no auto-nav — page changes are jarring).
  Submitted entries stack in a live "added" feed; field clears for the next →
  rapid successive adds. Return to Today is manual.
- **"Thinking" state = skeleton/shimmer fills in place**; resolved values fade in
  where the placeholder was. No layout shift.
- **Today owns the timeline** (canonical record). Log feed is transient.
- **Correction = universal slide-up sheet** from any item (no page change).
- **needs_clarification = ask inline, non-blocking**; entry shows a gentle "needs a
  detail" affordance, tap → sheet; NOT counted in totals until answered. Fatty
  never fabricates a number.

**Barcode + label capture [RESOLVED]:** the camera is a full-screen cover the user deliberately invokes from the Log page (an intended modal, not a jarring side-effect nav), dismissing back to Log.
- **Barcode = fast-add (high trust):** on a successful scan the product resolves and lands directly in the Log feed / timeline like any entry (provenance 📷 barcode), correctable afterward via the sheet. Barcode NOT found → fall back to the NL composer (prefilled / 'describe it instead'), not a dead end.
- **Label = capture-then-confirm (OCR is fallible):** capture the nutrition label, then show a quick confirm of the parsed values ([Looks right ✓] / edit) before it's added (provenance 📷 label). Unreadable / failed OCR → offer retake or type it. This keeps OCR misreads out of the day's totals — Fatty never silently trusts a fallible parse.

**Onboarding [RESOLVED]:** goal-led 3-step (goal+pace → measurements → target
reveal) → Today. Units/timezone auto-detect; metabolic formula defaults. Returning
users (persisted token) skip to Today. (This captures the GOAL the target calc needs.)

## 4. Today screen
- **Hero [RESOLVED]:** calories **consumed vs target** only — bold number + slim
  linear bar ("1,240 / of 2,000 kcal · 62%"). Single focus.
- **Secondary tier [RESOLVED]:** macro chips (P/C/F), then a distinct "🔥 burned"
  exercise line. Exercise is NOT in the hero and NOT a 4th macro.
- **Timeline [RESOLVED]:** items-forward, grouped into **time clusters** (entries
  within a ~10–15 min grace window combine, text-message-chain style). Items show
  name · kcal · **always-on source icon**. Raw phrase **only on tap** (item sheet).
- **Empty state [RESOLVED]: full budget + gentle invite.** Before anything is logged the hero shows the full target as available ('0 / 2,000 kcal · 2,000 to go') in a calm neutral tone — never an alarming empty zero; the bar is an empty track. The timeline shows one soft invite line ('Log your first thing') anchored to the Log CTA. Status-first and oriented, not blank, not a coachy illustration.
- **Corrected-value marking [RESOLVED]:** a user-corrected item simply carries the '✎ edited' source icon in the timeline (consistent with the provenance principle — no special-case treatment); the sheet's evidence block can note the original→corrected change ('You changed 280 → 420').
- **'Needs a detail' indicator [RESOLVED]:** a needs_clarification entry sits in the timeline with muted/de-emphasized styling and a gentle inline 'needs a detail' tag; it is visibly uncounted toward totals until answered, and tapping it opens the sheet in clarify-mode (see §4a).

### 4a. Detail / correction sheet  [RESOLVED]
- **Primary correction lever [RESOLVED]: portion/quantity-first.** The sheet leads with an amount stepper ('1 cup' → '1.5 cups'); kcal + macros recompute live from the source's per-unit data, so provenance stays intact (it does NOT become a manual 'edited' override just for fixing the amount). Direct value override is a secondary/advanced disclosure ('› Override values directly'). Matches how people actually mis-estimate.
- **DATA-MODEL IMPLICATION (for the contract/decomposition):** an entry must persist the source's per-unit nutrition + the chosen amount/unit, not just computed totals — so the stepper can recompute. This is a likely contract/data-model change (allowed pre-v1); it roots the DAG for the correction-sheet stories.
- **Wrong-match correction [RESOLVED]: a '› Change match' affordance.** Separate from the amount stepper. Tapping it reveals alternative source matches inline plus a 'Search…' fallback; picking a new food re-aims the entry and recomputes amount + values from the new source (provenance updates honestly to the new source). This is the SECOND correction lever — the stepper fixes a wrong amount, Change-match fixes a wrong food — so a misheard 'turkey'→'chicken' is fixed without delete-and-retype, and the entry keeps its place in the timeline. Direct '› Override values' remains the advanced third lever (sets provenance to user-edited).
- **Evidence / provenance block [RESOLVED]: source line + your words + (for estimates) a refine nudge.** Every sheet shows the source label & icon and the matched entry name (e.g. '🔍 USDA · Turkey breast, roasted', '📷 Label scan', '✎ You edited'), plus the user's original phrase quoted ('You logged: "turkey breast"'). A rough estimate is treated distinctly: '≈ Rough estimate' + the phrase + an explicit '› Make it exact' nudge that routes into Change-match. Compact and calm (not a dense clinical panel) — honest about where the number came from, and it actively lifts the lowest-trust items rather than hiding them. (Pays off the 'evidence one tap away' principle.)
- **needs_clarification clarify-mode [RESOLVED]: Fatty's question + quick-pick chips + free-text fallback.** Tapping a 'needs a detail' entry opens the sheet in clarify mode showing the specific question Fatty needs answered (e.g. 'What milk?') with the likely answers as tappable chips ([Whole][Skim][Oat][Almond]) plus a 'type your own' fallback. One tap resolves → the entry recomputes and starts counting toward totals (it was uncounted while pending, per §3). Fast, NL-feeling, calm; Fatty never fabricates the missing detail.
- **Save-as-food [RESOLVED]: manual '› Save as food' action in the sheet.** Saves the current (corrected) item with its per-unit definition so it surfaces in the Log typeahead later. Explicit, no auto-prompt/nagging (calm). Smart 'save this for next time?' suggestions are parked for v2.
- **Detents [RESOLVED]: medium default → large on demand.** Opens at a medium detent showing the common case (item header + amount stepper + evidence + primary actions); expands to large only when Change-match search or the value-override fields open. Native iOS sheet behaviour; the timeline stays partly visible behind for the quick-fix case.

## 4b. Trends screen  [RESOLVED — minor viz details deferred]
- **Focus / hierarchy [RESOLVED]: weight outcome up top, intake behavior below.** Lead with a smoothed weight-trend line drawn over the noisy daily weigh-in points, with a range selector (e.g. 30d) and the headline delta ('182.4 lb · ↓1.8 this month'). Beneath it, an intake-adherence summary over the same range (avg kcal vs target, days-on-target count, a compact adherence strip). Weight is 'secondary' in the daily loop, but it's the outcome users open Trends to check; intake sits right beneath as the 'why'. Keeps the outcome↔behavior link on one screen (no segmented toggle that severs it).
- **Past-day drilldown [RESOLVED default]:** tapping a day in the intake history opens that day's timeline (the Today layout for that date), so history is browsable down to the entries.
- **Weight-logging entry [RESOLVED]: from the Trends weight card, with an occasional cadence-based reminder.** A '+ log weight' on the weight card opens a small numeric entry sheet (defaults to today, seeded with the last value). Weight logging is NOT added to the status-first Today screen and NOT buried in Profile. CRITICAL STANCE (per user): Fatty must NOT encourage scale-watching — we want the user to weigh in only *occasionally*, enough to feed a meaningful trend, never daily. So: the weigh-in reminder is low-frequency and only fires when a weigh-in is actually *due* for the trend (gentle nudge, never a daily prompt, no weigh-in 'streak'), and the UI leads with the smoothed trend line + delta, de-emphasizing any single day's reading. (See the new 'Encourage the trend, not the scale' philosophy principle.)
- **Weigh-in cadence [RESOLVED — research-backed]: default WEEKLY, user-adjustable.** Default reminder is weekly; the user can change it at onboarding / in settings (Weekly · Every 2 weeks · Monthly · Off). Evidence basis (deep-research pass): a meta-analysis of RCTs found daily and weekly weighing produce indistinguishable weight loss (~−3.4 kg either way), so weekly captures the full outcome benefit; ~4 readings/month is enough for a meaningful smoothed trend; and the documented psychological harm of self-weighing is DAILY-specific and concentrated in at-risk subgroups (younger women, binge-eating/body-image concerns). Benefit appears when weighing is wrapped in trend feedback, not naked numbers — which matches our 'lead with the smoothed trend' design. Reminder only fires when a weigh-in is actually due; never daily, no streaks.
- OPEN (Trends): exact range options; macro history depth.

## 4c. Profile / Settings  [RESOLVED — account/self-host deferred to Sign-in area]
- **Role & structure [RESOLVED]: a 'control panel for your numbers', not a generic settings dump.** Opens from the persistent header gear as a native grouped settings screen, but it LEADS with the numbers the whole app depends on:
  - **YOU:** Goal (lose/maintain/gain + pace), Calorie target (+ how it's derived, with visible provenance), macro targets.
  - **BODY:** weight, height, age, sex, activity level (the metabolic-formula inputs).
  - **PREFERENCES:** units, weigh-in reminders, notifications, appearance (follows system).
  - **ACCOUNT & SERVER:** sign-in/session, self-host server connection, sign out.
  - **DATA & ABOUT:** export/delete, about/version.
  Mirrors the inputs onboarding captures (goal+pace → measurements → target), so Profile is where you edit them later.
- **Calorie target [RESOLVED]: derived by default, with a clearly-marked manual override.** Default target is computed from goal + pace + body metrics via the metabolic formula, displayed WITH its provenance ('└ from your goal + metrics'). Editing goal/pace/metrics recomputes it and shows a mini target-reveal (the onboarding reveal, in miniature). The user can set a manual override, which is then marked '✎ set by you' with a [Reset] back to the derived value. This applies the 'every number shows where it came from' principle to the target itself — same provenance pattern as timeline items (derived vs user-edited).
- **Macro targets [RESOLVED]: auto-derived from the calorie target + goal, with a marked override.** Sensible defaults (protein anchored to bodyweight, the rest split), shown with provenance ('└ from your target'); the user can override the split/grams, which is marked '✎ set by you' with a [Reset]. Same pattern as the calorie target — most users never touch it. (This is what the Today P/C/F chips measure against.)
- **Units / appearance / notifications [RESOLVED — conventional defaults]:** Units auto-detect from locale, overridable (metric/imperial; kg/lb; kcal). Appearance follows system by default with an explicit Light/Dark/System override. Notifications are minimal and calm — opt-in, NO daily-logging nag and NO streaks (per the anti-nag/calm stance); the only standing nudge is the occasional weigh-in reminder (default WEEKLY, user-adjustable Weekly/Every-2-weeks/Monthly/Off — see §4b).
- DEFERRED: account/session + self-host server connection are designed in the Sign-in area (§4d).

## 4d. Sign-in & self-host connection  [RESOLVED]
- **Connection & auth model [RESOLVED]: self-host-first, with accounts on your own server.** First run: (1) 'Connect to your Fatty server' — enter or scan the server URL; (2) Sign in or Create account on that server (email + password); (3) → onboarding → Today. The session token persists (per FTY-090) so returning users skip straight to Today (matches §3 onboarding). Accounts live on the user's OWN server — there is no hosted Fatty instance pre-v1. The LLM provider's subscription login (per the subscription-not-API-keys stance, FTY-086/087/088/089) is a SERVER-SIDE setup concern, separate from this user-facing sign-in.
- **Setup QR [RESOLVED]: carries the server URL only (no embedded secret).** Scanning connects the app to the server; the user still creates the account with email + password manually. Chosen for a simpler, safer QR (no single-use token to leak/expire); the small cost is a sign-up form to type. Manual URL entry remains the fallback for users who can't scan.
- DEFERRED: connect / sign-in / create-account screen detail + error states (server unreachable, bad credentials) fold into the global States & edges pass (§6).

## 5. Visual & tone  [RESOLVED — except 2 sourcing details]
- **North star:** iOS-native, ultra-modern, premium, calm — NOT a generic calorie app.
- **Tab bar [RESOLVED]: standard native 3-tab bar, no center ⊕.** Plain UITabBar — Today · Log · Trends, three equal SF-Symbol tabs. The tentative raised center ⊕ is killed: it would restyle system chrome, violating the new 'Native skeleton, bespoke soul' principle. Logging stays one tap away via the Log tab AND the primary CTA on the Today hero.
- **Aesthetic [RESOLVED]: minimal monochrome + one accent** (neutral canvas, airy
  whitespace, crisp bold type, single accent for actions/emphasis/progress).
- **Accent [RESOLVED]: warm amber / honey** — the single accent (monochrome canvas otherwise). Used for the Today hero progress bar, primary actions, and emphasis. Chosen to be distinctive and premium-calm — deliberately NOT the generic health-app green and NOT iOS system blue. The hero bar fills amber toward the calorie target ('on track'); true over-budget gets its own warning tint (to be defined in states).
- **Light/dark [RESOLVED]: both, system-following; dark = elevated charcoal.** Dark mode uses iOS-native layered greys (≈#1C1C1E base, ~#2C2C2E raised cards), near-white text — soft, calm, premium; the amber accent glows warmly rather than blaring. NOT pure-OLED-black (too harsh vs 'calm by default'). Dark is a first-class, bespoke-tuned surface, not a mechanical inversion.
- **Typography [RESOLVED]: custom display face for hero numerals + headers, SF Pro for body.** A bespoke display typeface carries the hero calorie number and section headers; body/UI text stays SF Pro (Dynamic Type, native). This is a deliberate brand choice that consciously departs from strict 'prefer native' — flag for a possible philosophy amendment. CONSTRAINTS: the display face MUST have tabular/monospaced figures (the hero number updates live as you log — it must not jitter width), must be licensable + bundle-able in the app, and must hold up at very large sizes.
  - Face character = MODERN GEOMETRIC GROTESQUE — clean, confident, ultra-modern sans with subtle warmth (Aeonik / Söhne / GT-Walsheim family of feel), wide tabular numerals, tight header tracking. Quietly distinctive, pairs cleanly with SF Pro body, never loud. Still TBD: the exact licensed font pick (must meet the tabular-figures + licensing/bundling + large-size constraints already noted).
- **Materials & depth [RESOLVED]: restrained system materials.** Use iOS blur only where iOS naturally blurs — tab bar (.ultraThin), slide-up correction sheets (frosted; content behind dims), large-title nav header frosts on scroll. Timeline cards stay flat opaque. Layered and native, but calm — no vibrancy-heavy 'glass everywhere'.
- **Motion & haptics [RESOLVED]: restrained by default + a few signature moments.** Default motion is quiet and physical — short spring transitions, in-place fades (skeleton → value), the hero bar eases as it fills; no layout shift (per 'calm by default'). Identity lives in a SMALL set of designed signature beats with matching haptics: an entry resolving (shimmer → value + soft tap), a correction saved, the calorie target reached (gentle pulse + success haptic). Calm ~95% of the time, branded at the few beats that matter. (Motion is one of the sanctioned identity carriers per the new 'Native skeleton, bespoke soul' principle.)
- DEFERRED (sourcing/state details, not blocking the design): over-budget warning tint → resolve with Today states; exact licensed display font pick → sourcing task.

## 6. States & edges  [RESOLVED]
- **Offline / server-unreachable logging [RESOLVED]: queue raw, resolve on reconnect.** The user can still capture text offline; it stacks as a PENDING entry (uncounted, with an offline indicator) and auto-parses + counts once the server is reachable — reusing the pending / needs_clarification pattern (capture the thought now, keep the number honest). A gentle connection banner shows status. Never blocks capture, never fabricates a number. BACKEND IMPLICATION (for decomposition): an offline outbox/queue + sync, and entries that can exist in a pending-unparsed state — note for the contract/data-model story.
- **Over-budget hero [RESOLVED]: amber fills to target, coral over-segment past it.** The bar fills amber to 100% at the target line, then a distinct coral over-segment extends beyond it; the copy flips 'X to go' → 'X over'. Both the within-budget and over portions stay visible in one bar. Calm but unambiguous — informs, doesn't flash or scold. This is the single sanctioned warning color in the monochrome+amber system, and it is always paired with the 'over' text (never color-alone, so it's accessible).
- **Remaining edge states [RESOLVED — principled defaults]:** (a) Per-entry parse/LLM error → the entry shows a gentle inline 'couldn't read that' with Retry + edit-as-text; uncounted, never a crash, never a fabricated number. (b) Trends empty (no weight/history yet) → calm invite ('Log your first weigh-in' on the weight card; intake history appears once days are logged) — same tone as Today empty. (c) Log empty → just the keyboard-up composer (no recents in v1, per §3). (d) Sign-in errors → server unreachable shows 'Can't reach [server] · Retry'; bad credentials is an inline field error; never a dead-end. (e) Loading → skeleton/shimmer in place (per §3).

## 7. Cross-cutting  [RESOLVED]
- **Accessibility:** full Dynamic Type (SF Pro body scales; the bespoke geometric-grotesque hero number scales within sane bounds); VoiceOver labels on every provenance icon and the hero ('1,240 of 2,000 kcal, 62%, 760 remaining'); never color as the sole signal (over-budget pairs the coral over-segment with 'over' text; sources are icon + accessible label); ≥44pt tap targets; respects Reduce Motion (the signature motion beats degrade to simple fades). Target WCAG AA contrast.
- **Device scope:** iPhone, all sizes (SE → Pro Max), portrait-first. No iPad- or landscape-specific design in v1 — scales gracefully but is not optimized for them.
- **Performance feel:** optimistic + in-place always; skeleton appears fast and resolves in place with no layout shift; long timelines virtualized.
- **Privacy-visible:** data lives on the user's OWN server (self-host); the app is explicit about where data goes; provenance reinforces the transparency stance.

## Philosophy principles seeded this session (in `docs/design-philosophy.md`, auto-enforced)
1. iOS-native & ultra-modern — not a generic calorie app.
2. Calm by default — never jar the user.
3. Every number shows where it came from (visible provenance icon; evidence on tap).

## Remaining to design (then write the doc → decompose to single-boundary stories)
- Today: detail/correction sheet, empty state, "needs a detail" indicator.
- Log: barcode + label capture flows.
- Trends (weight + history); Profile/Settings (gear); sign-in & onboarding screens.
- Visual sub-decisions (accent, light/dark, type, materials, motion, tab treatment).
- States & edges (empty/error/offline); cross-cutting (a11y, dark mode, perf feel).

## v2 / parked
- Smart context-aware food recommender on the Log page (time-of-day/patterns,
  Spotify-style) — replaces a naive recents list. Not v1.

## Cleanup pending (in public `fatty/`, from the earlier dogfood detour — REVERT before any commit)
- `fatty/mobile/app.config.js` (new untracked) — delete.
- `fatty/mobile/state/session.ts` — revert the temp dogfood-token shim to `return null;`.
- App + docker backend may still be running locally (iPhone 17 sim, API :18000).
- Candidate stories from the dogfood pass: FTY-090 / FTY-091 (mobile auth), unpromoted.

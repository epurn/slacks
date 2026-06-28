# Fatty Design Philosophy

This is the living record of how Fatty should look, feel, and behave — the
product's taste, written down. It is maintained by the `polish` skill (see
`.claude/skills/polish/`) during dogfooding sessions and is **auto-enforced**:
the steward embeds it into every author assignment, and the reviewer checks each
PR against it. Updating a principle here changes what the agents build and what
the reviewer will block — no code change required.

> **If you are an author or reviewer reading this embedded in your prompt:**
> treat the principles below as product requirements, the same weight as the
> security and contract rules. The **Foundational stance** is always active. The
> **UX / design principles** are the project's accumulated taste — honour them
> when they apply to your change; if none apply, this section is informational,
> not a checklist to force.

## How this document works

- **One principle = one rule + the sensibility behind it.** A principle is not a
  ticket; it is a durable preference that should hold across many features.
- Principles are distilled from real feedback during use. A one-off "move this
  button" becomes a fix story, not a principle. It becomes a principle only when
  it expresses a rule that should generalize ("interactions should cost the
  fewest taps that are still unambiguous").
- The `polish` skill transcribes principles the user states directly, and may
  **occasionally propose** a principle it infers from a cluster of related
  complaints — proposals are always confirmed with the user before they land here.

## Foundational stance (always active)

### Pre-v1: prefer the correct redesign over a compatible patch

Fatty is pre-v1 with **no users**. There is nothing to migrate and no behaviour
to preserve for compatibility. When a change implies the current data model,
contract, or architecture is wrong, **change it** — do not paper over it with an
additive shim in the layer you happen to be working in. A UX change that reveals
the model is wrong should reach down and fix the model.

- **Why:** the priority is a clean, polished product and a clean codebase.
  Compatibility debt accrued now has to be unwound after launch; redesign now is
  cheap because nothing depends on the old shape.
- **How it applies:** breaking behaviour, schemas, and contracts is allowed and
  expected when it yields the better design. The planner decomposes such changes
  into properly-laned stories (e.g. a contract/data-model story first, then the
  dependent backend/frontend stories) — the author still implements one scoped
  slice, but that slice is allowed to be a breaking one when the spec says so.

## UX / design principles

### Native skeleton, bespoke soul

Be unmistakably iOS-native in *structure and behaviour* — navigation, system materials/blur, sheets and detents, Dynamic Type, haptics, standard controls — and concentrate brand identity in a small set of *expressive* carriers: the display typeface, the single warm accent, and a few signature moments (e.g. the Today hero). Never buy identity by restyling system chrome or inventing non-native interactions.

- **Why:** native structure earns instant trust and muscle-memory; identity earned through expression — not by fighting the platform — is what separates premium from generic without ever feeling "off." A user shouldn't be able to say *why* it feels custom; the chrome is all native, but the type, the warmth, and the signature moments are pure Fatty.
- **Applies to / examples:** prefer system navigation, controls, sheets, and materials; express brand through the display type, the amber accent, and hero moments. Anti-patterns it forbids: custom-styled tab bars, restyled system switches/sliders/pickers, and bespoke non-native gestures that fight platform muscle-memory.

### iOS-native and ultra-modern — not a generic calorie app

Fatty should feel like a polished, modern, **native iOS app** — built from iOS
idioms and patterns — not like a typical calorie tracker. When an iOS-native
pattern and a convention borrowed from other calorie/nutrition apps conflict,
choose native.

- **Why:** the brand and the wedge are "this doesn't feel like MyFitnessPal." A
  native, modern feel *is* the differentiator and sets the polish bar.
- **Applies to / examples:** prefer native components, navigation, system
  materials/blur, SF Symbols, Dynamic Type, large titles, sheets with detents,
  haptics, dark mode, generous whitespace, and bold but restrained typography.
  Avoid dense data tables, cluttered food-database-search screens, and the visual
  language of legacy calorie apps.

### Calm by default — never jar the user

The interface must never jar the user. Don't pull them to another screen as a
side effect of an action, and don't let the layout jump or reflow when async work
resolves — state changes arrive **in place**, gently.

- **Why:** an app that moves under you feels unstable and cheap; composure is what
  makes a modern native app feel trustworthy and premium.
- **Applies to / examples:** async results fill a placeholder in place (skeleton →
  fade-in) with no layout shift; corrections and detail actions happen in slide-up
  sheets, not navigations; submitting a log keeps you where you are. Avoid surprise
  navigation, content that shoves other content around, and spinners that swap into
  differently-sized content.

### Every number shows where it came from

Each value Fatty presents carries a **visible provenance indicator** — a small,
always-on icon for its source (trusted database, barcode, label scan, saved food,
the user's own correction, or a rough estimate). The full evidence is one tap
away. Trust comes from showing where a number came from, not from a confidence
score.

- **Why:** the product's credibility rests on transparency; a number with no
  visible origin is just another opaque tracker guess. Provenance at a glance is
  how trust — and the value of correcting — compounds.
- **Applies to / examples:** items carry an always-visible source icon (icon only,
  no clutter; detail on tap); rough estimates are visibly distinguishable from
  trusted / saved / edited values; prefer a concrete source over an abstract
  confidence %. Keep it quiet so it stays calm.

### Encourage the trend, not the scale

Nudge occasional, cadenced weigh-ins (default weekly, user-adjustable) and lead with the smoothed weight trend, never the day-to-day number. Never reward daily weighing — no streaks, no daily prompts, no scale-watching.

- **Why:** the evidence is clear (deep-research pass): weekly weighing captures the full weight-loss benefit (RCT meta-analysis: daily ≈ weekly, ~−3.4 kg either way), while daily weighing's documented psychological harm — raised stress, negative-affect lability, disordered-eating onset — is daily-specific and concentrated in at-risk subgroups (younger women, people with binge-eating/body-image concerns). Self-weighing helps when it's wrapped in trend feedback, not naked numbers. So the healthy AND effective design is occasional weigh-ins surfaced as a trend.
- **Applies to / examples:** weigh-in reminders are low-frequency and fire only when a reading is due (default weekly; never daily); Trends emphasizes the smoothed trend line + delta over any single reading; the daily weight number is de-emphasized. Anti-patterns it forbids: daily weigh-in prompts, weigh-in 'streaks', leaderboards or any mechanic that rewards stepping on the scale more often.

### Evidence-backed by default

Every default, recommendation, and number Fatty gives the user should be grounded in the best available science — not folk wisdom, guesswork, or copied-from-competitors convention. When the product sets a default or makes a health/nutrition/behaviour claim (calorie targets, macro splits, deficit/pace rates, weigh-in cadence, habit nudges), it should reflect the actual evidence, and be transparent about that basis where it helps.

- **Why:** the product's credibility and the user's real results depend on guidance that is actually true. "Science-backed" is part of the trust wedge, right alongside visible provenance — an evidence-grounded default earns trust the same way a sourced number does.
- **Applies to / examples:** defaults derive from established formulas / evidence (metabolic equations, evidence-based deficit rates, weekly weigh-ins per the trend principle); avoid fad-diet defaults and unsupported claims; surface the basis where it aids trust. Planning and design decisions that turn on a factual question are settled by research, not assertion (see the planning skills' background-research practice).

<!--
  More principles accrue here from design + polish sessions. Template:
  ### <short imperative title>
  <the rule, stated plainly>
  - **Why:** <the sensibility behind it>
  - **Applies to / examples:** <where it bites; an anti-pattern it forbids>
-->

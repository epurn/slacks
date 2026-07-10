# FTY-236 — End-of-Sweep Visual Audit: Correction sheet

In-depth, eyes-on visual verification pass of the **Correction sheet** after the
accent-as-text (FTY-207..212 / FTY-208) and type-scale (FTY-213..217 / FTY-214)
mechanical sweeps. Evidence only — **no product code changed**; observed defects
are filed as planner notes, not fixed here.

## How this evidence was captured

Captured on the iOS simulator (iPhone 17, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driven purely through the **FTY-247 visual-review
deep-link entry point** with FTY-263's correction sub-state presets — no manual
RC-backend state walking, no live personal data. Each preset opens the correction
sheet **directly in its mode** over the synthetic resolved "Oatmeal" entry (140
kcal · USDA), the same hermetic fixture `correction.yaml` uses. Both themes are
forced through the deep link's `&theme=light|dark` param (`useVisualReviewTheme`),
so each state is captured in a genuine forced light and dark render.

| State (Scope) | Preset | Deep link | Light | Dark |
|---------------|--------|-----------|-------|------|
| Correction sheet over a resolved entry (`normal`) | `correction.detail` | `fatty://__visual-review?preset=correction.detail&theme=<t>` | `correction-detail-light.png` | `correction-detail-dark.png` |
| Change-match typeahead suggestion flow | `correction.typeahead` | `fatty://__visual-review?preset=correction.typeahead&theme=<t>` | `correction-typeahead-light.png` | `correction-typeahead-dark.png` |
| Advanced override panel (filled, awaiting Apply) | `correction.confirm_apply` | `fatty://__visual-review?preset=correction.confirm_apply&theme=<t>` | `correction-confirm-apply-light.png` | `correction-confirm-apply-dark.png` |

The `correction.typeahead` presets open the Change-match panel at the large,
dimmed detent with its candidate list **already loaded** ("Chicken, grilled,
USDA · 165 kcal / 100g") — the loaded sub-state, not a blank/loading frame.

## Accent-as-text sites on the Correction sheet

The sweep converted text-rendered accent sites from `colors.accent` (the
decorative amber, tuned for fills/bars) to `colors.accentText` (the amber tuned
to meet WCAG AA as text on both surfaces). Button **fills** correctly keep
`accent` with `accentForeground` on top — they are not text sites.

| Site | Source | Token | Seen in |
|------|--------|-------|---------|
| "Done" (close) | `CorrectionSheet.tsx:235` | `accentText` | all 6 |
| "Change match" lever | `CorrectionSheet.tsx:300` | `accentText` | detail, confirm_apply |
| "Cancel" (change-match) | `correction/ChangeMatchPanel.tsx:52` | `accentText` | typeahead |
| "Make it exact" nudge | `correction/ProvenanceBlock.tsx:63` | `accentText` | rough-estimate only — n/a for the USDA fixture, not in these captures |
| "Saved" (save-as-food) | `correction/SaveFoodRow.tsx:35` | `accentText` (saved state only) | idle in these captures |
| "Save" (override) | `correction/OverridePanel.tsx:97,103` | `accent` fill + `accentForeground` label — **button, not text** | confirm_apply |

Rendered token values (`mobile/theme/colors.ts`): light `accentText` `#92400E`,
dark `accentText` `#F5A623`. The sheet body is `surfaceRaised` (light `#FFFFFF`,
dark `#2C2C2E`). Measured contrast of `accentText` against `surfaceRaised`:
- light `#92400E` on `#FFFFFF` ≈ **7.1:1** (AA large & normal text ✓)
- dark `#F5A623` on `#2C2C2E` ≈ **6.9:1** (AA large & normal text ✓)

Both exceed the 4.5:1 AA normal-text bar. (`mobile/theme/theme.test.ts` also
gates `accentText` ≥4.5:1 against `surface` in both palettes; `surfaceRaised` is
a lighter/darker step that keeps the ratio ≥ that bar.)

## State-by-state verdict

| State | Theme | Accent-as-text = `accentText`, AA-legible | Type on `typeScale`, no clip/wrap/regression | Verdict |
|-------|-------|-------------------------------------------|----------------------------------------------|---------|
| detail | light | ✅ "Done" + "Change match" dark-amber, legible on white | ✅ headline title, callout labels, portion `1 cup` / `140 kcal · P5 C27 F3`, ADVANCED rows — clean | **PASS** |
| detail | dark | ✅ "Done" + "Change match" bright-amber, legible on charcoal | ✅ same layout, no clip | **PASS** |
| typeahead | light | ✅ "Done" + "Cancel" dark-amber; "Change match" header is plain text (correct) | ✅ panel header, search field, candidate name + `165 kcal / 100g` — clean | **PASS** |
| typeahead | dark | ✅ "Done" + "Cancel" bright-amber, legible | ✅ same, no clip | **PASS** |
| confirm_apply | light | ✅ "Done" + "Change match" dark-amber; "Save" is amber **fill** with dark `accentForeground` label (button) | ✅ "Override Calories" headline, footnote note, `140` input, kcal unit — clean | **PASS** |
| confirm_apply | dark | ✅ "Done" + "Change match" bright-amber; "Save" fill legible | ✅ same, no clip | **PASS** |

**Sweep outcome: PASS in all six captures.** Every accent-as-text site on the
Correction sheet renders `accentText` and reads AA-legible against its surface in
both light and dark; type renders on the `typeScale` tokens with no clipped,
wrapped, truncated, or mis-sized text versus the pre-sweep layout.

## Defects observed

None that are sweep-caused or block the sweep outcomes.

One borderline item was considered and **deliberately not filed**: the override
helper copy `Marks this entry "✎ edited"` (`OverridePanel.tsx:47`) uses the
U+270E pencil dingbat. It renders as a consistent monochrome glyph (not a
colourful platform emoji), it is inline descriptive copy rather than navigation/
header/control chrome, and it mirrors the UX design doc's own "✎ edited"
provenance shorthand (`docs/design/ux-design.md` §4). It does not read as
unfinished in the running app, so it is not a "No emoji as UI chrome" violation
worth a story. Recorded here for the reviewer's visibility.

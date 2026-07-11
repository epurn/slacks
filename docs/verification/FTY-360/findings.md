# FTY-360 — Timeline inline-tag row reflows at Larger Accessibility sizes

Running-app evidence that the shared `ItemTimelineRow` no longer starves its
name/question column at the Larger Accessibility Dynamic Type sizes. Captured on
a leased headless iOS simulator (Slacks-Slot-0, iPhone 17, iOS 26.5) serving
this branch's JS in E2E mode, through the FTY-247 visual-review preset
`today.partially_resolved` (the FTY-330 mixed-log state whose item-scoped
pending-question row — "How much hummus?" — is the row that wraps).

The active iOS content-size category was driven externally with
`xcrun simctl ui <udid> content_size <size>` (the same OS Dynamic Type signal the
component reads via `useWindowDimensions().fontScale`), not a hardcoded width:

- **standard** = `content_size large` (default; fontScale ≈ 1.0)
- **accessibility-extra-large** = `content_size accessibility-extra-large`
  (fontScale ≈ 2.35, well above the 1.5 reflow cutoff)

Both themes were forced by the preset's `&theme=light|dark` param.

## Screenshots

| Size | Light | Dark |
| --- | --- | --- |
| Standard (default…xxxLarge) | ![std light](partial-standard-light.png) | ![std dark](partial-standard-dark.png) |
| accessibility-extra-large | ![ax light](partial-ax-extra-large-light.png) | ![ax dark](partial-ax-extra-large-dark.png) |

## What the evidence proves (acceptance criteria)

- **Standard Dynamic Type is unregressed — single horizontal line.** In both
  standard captures the pending-question row renders exactly as before: the
  provenance icon, the "How much hummus?" text, the "needs a detail" tag, and the
  right-aligned em-dash all sit on one horizontal line, and the resolved "Greek
  yogurt · 140 kcal" sibling is a single line with the reserved kcal column. The
  layout matches the FTY-330 clean baseline byte-for-behaviour.
- **At the Larger Accessibility size the text wraps by word, never one glyph per
  line.** In both accessibility-extra-large captures the row reflows to a vertical
  stack: the question "How much hummus?" uses the full row width and wraps cleanly
  by word ("How much" / "hummus?"), and the "needs a detail" tag + em-dash reflow
  to a second line beneath it. The pathological one-character-per-line collapse is
  gone. The resolved "Greek yogurt" row likewise keeps its name on its own line
  with "140 kcal" reflowed right-aligned beneath it.
- **Every row variant, tag copy, provenance glyph, and value is preserved** —
  only the arrangement changes at AX sizes. The provenance icons
  (magnifying-glass for the trusted "Greek yogurt", question-mark for the open
  component), the muted uncounted treatment, the "needs a detail" tag, and the
  em-dash are all intact.
- **Light + dark both legible** at both sizes.
- **Reduce Motion unaffected** — the fix introduces no motion; it is a static
  layout branch keyed on the content-size category.

## Reproduce

Serve this branch's JS in E2E mode on a leased simulator, then:

```
# standard size:
xcrun simctl ui "$SLACKS_SIM_UDID" content_size large
maestro --udid "$SLACKS_SIM_UDID" test -e SIZE=standard capture.yaml

# accessibility size (scrolls the timeline into view first):
xcrun simctl ui "$SLACKS_SIM_UDID" content_size accessibility-extra-large
maestro --udid "$SLACKS_SIM_UDID" test -e SIZE=ax-xl capture-ax.yaml
```

Each flow opens `fatty://__visual-review?preset=today.partially_resolved&theme=light|dark`,
waits on the `visual-review-settled:today.partially_resolved` marker, and shoots
the settled frame.

## Component coverage

`mobile/components/ItemTimelineRow.test.tsx` — the "Larger Accessibility reflow
(FTY-360)" describe block drives the content-size signal through the same
`useWindowDimensions().fontScale` public surface (via `Dimensions.get`) and
asserts: at standard size the row is a single horizontal line (name and kcal
share a parent, reserved 64 pt kcal column intact); at an AX size the row stacks
(`flexDirection: column`), the wrapping question keeps `flex: 1` and its
word-wrap (`numberOfLines` undefined), and the tag/kcal reflow to a separate
parent from the name. Read-only past-day and resolved variants are covered too.

## Round 2 — loading-skeleton footprint parity at AX sizes

Round 1 review flagged that the reflowed **loading skeleton** did not match the
resolved stacked-row footprint: its second-line kcal placeholder sat at the left
of the line while the resolved row's kcal value (`kcalStacked`: `flex: 1` +
`textAlign: "right"`) sits at the far right, so a pending row could still jump
horizontally when it resolved at Larger Accessibility sizes.

Fix: the loading branch now wraps the fixed-width kcal placeholder in a
`kcalSkeletonStacked` container (`flex: 1`, `alignItems: "flex-end"`), landing it
in the exact spot the resolved right-aligned value occupies — zero horizontal
jump on resolve. A new test in the FTY-360 block renders the loading variant at
an AX `fontScale`, asserts the loading row stacks (matching the resolved row) and
that the kcal placeholder wrapper is `flex: 1` + `flex-end`, mirroring the
resolved `kcalStacked` value's `flex: 1` + `textAlign: "right"`.

No new simulator capture: this fix does not alter the pending-question row shown
in the screenshots above (that row never renders the loading skeleton), so the
committed visual matrix remains valid. The loading skeleton is a transient
estimating state; its footprint parity with the resolved row is a layout-geometry
property, proven deterministically by the added component test rather than a
momentary screenshot.

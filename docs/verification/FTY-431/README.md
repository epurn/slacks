# FTY-431 — Trends adherence off-target cell: running-app evidence

Captured on the iOS simulator (iPhone-class, iOS 26.5) against the E2E debug
binary (`EXPO_PUBLIC_SLACKS_E2E=true`), driving the committed
`mobile/.maestro/adherence-strip-fty431.yaml` flow. Both shots use the
`trends.adherence_mix` visual-review preset (registered from the Trends lane in
`mobile/components/trends/visualReviewPresets.ts`), whose newest days carry all
four adherence-cell states, so a single strip frames **on-target, off-target,
no-target and no-data** side by side. Every assertion in the flow passed on this
run, in both themes.

The change: the off-target cell no longer paints a 2 pt `surface`-colored ring.
Its non-color cue is now the cell's silhouette — **square corners** against
every other state's rounded `CELL_R` cap.

| Screenshot | Theme | Proves |
|------------|-------|--------|
| `trends-adherence-dark.png` | dark | The coral off-target bars carry **no near-black ring** (dark `surface` is `#1C1C1E`, the outline the operator flagged) and read as clean, deliberate bars next to the amber on-target bars |
| `trends-adherence-light.png` | light | The same cells in light: no washed-out light ring; the coral bar is a plain fill, consistent with the amber one |
| `strip-detail-dark.png` | dark | 2× crop of the strip: the two coral cells are square-cornered, the amber / no-data / no-target cells keep their rounded caps — the non-color cue, visible with hue ignored |
| `strip-detail-light.png` | light | The same crop in light |

## Reading the strip

Left → right in both crops: **no-data** (muted `separator` fill) · **on-target**
(amber, rounded) · **off-target** (coral, square) · **no-target** (hollow, muted
hairline) · **on-target** · **off-target** · **on-target**. The strip
auto-scrolls to its newest end, so these are the most recent days.

## Accessibility

Cell labels are unchanged — the flow asserts `.*on target.*`, `.*off target.*`
and `.*no target set.*` are present in the accessibility tree before each
screenshot is taken, so a strip that had lost its VoiceOver labels (or was
missing a state entirely) would have failed before capture.

The colorblind-safe distinction between on-target and off-target survives the
ring's removal: both are solid fills, so the discriminator is the corner shape,
which carries no color of its own and therefore works identically in both
schemes. `mobile/theme/theme.test.ts` still holds the coral fill to the WCAG
1.4.11 non-text 3:1 threshold against the card background it sits on.

## Reproducing

```sh
cd mobile
maestro test .maestro/adherence-strip-fty431.yaml
```

against an installed E2E debug build (see `mobile/.maestro/README.md`). A cold
dev-client bundle can outlast the flow's 20 s settle wait — launch the app once
to warm the bundle before running the flow.

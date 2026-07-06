# FTY-262 — `today.confirm_parsed` visual-review seam: running-app evidence

Captured on the iOS simulator (iPhone, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), by running the **committed**
`mobile/.maestro/visual-review-smoke.yaml` flow end to end — the same flow
FTY-247 ships, extended in this story with the `today.confirm_parsed` step.

| Screenshot | Preset | Deep link | Proves |
|------------|--------|-----------|--------|
| `today-confirm-parsed-light.png` | `today.confirm_parsed` | `fatty://__visual-review?preset=today.confirm_parsed&theme=light` | Today's parsed-confirmation sub-state (the `ConfirmParsedValuesSheet`) opened purely through the E2E-only initial-state seam in `useLabelProposal` — no "Capture label" / "Take photo" / "Upload label" taps — showing the synthetic "Granola bar" parse (190 kcal · P4g C29g F7g), the "Label scan" provenance icon, and the "Not yet counted" badge |

## What the run proved

- The full smoke flow ran start to finish: `today.populated` (light) →
  `trends.populated` (dark) → `today.empty` (light) → `today.signed_out` (light)
  → `today.populated` again (the non-sticky signed-out regression guard) →
  `today.confirm_parsed` (light, this story) — every prior preset still passes,
  so the new preset does not perturb the existing FTY-247 flows.
- `today.confirm_parsed` reached the sub-state from a cold preset activation with
  **no scripted taps**: the deep link seeds the preset, the root layout remounts
  the navigator subtree, and `useLabelProposal`'s initial `useState` reads the
  active preset and seeds `labelProposal`/`labelProposalVisible` before the first
  paint.
- The preset's own `visual-review-settled:today.confirm_parsed` marker appeared
  and Maestro's `extendedWaitUntil` on it succeeded. This marker is rendered
  **inside the confirm sheet's own modal**, not by the shared
  `VisualReviewSettleOverlay` (FTY-247): the sheet's `Modal` sets
  `accessibilityViewIsModal`, which makes every other window's accessibility
  subtree — including the navigator-level overlay's marker — unreachable to
  Maestro for as long as the modal is presented. The fix (in
  `components/ConfirmParsedValuesSheet.tsx` + the `labelProposalSettledMarker`
  plumbed from `useLabelProposal` through `TodayScreen`/`TodaySheetHost`) renders
  the identical `visual-review-settled:<preset>` marker inside the modal's own
  subtree instead, so screenshot automation waits on it exactly like every other
  preset. Any future Modal-based sub-state seam (FTY-263..268) will need the same
  pattern if its sheet also sets `accessibilityViewIsModal`.
- The marker honours FTY-247's **network-quiet settle contract**, not merely the
  modal mounting: `useConfirmParsedSettledMarker` (in
  `components/today/visualReviewConfirmParsed.ts`) reuses the shared `QUIET_MS`
  window and fetch-tick channel, so the marker only appears once the Today
  data-load behind the sheet has gone quiet. That is why the committed
  `today-confirm-parsed-light.png` captures a fully-settled frame — the parsed
  "Granola bar" card over a loaded, empty Today — with **no dev "Refreshing…"
  overlay** and no mid-load state. (An earlier revision exposed the marker the
  instant the modal rendered, which let the screenshot catch a transient
  "Refreshing…" frame; gating on network-quiet is the fix.)
- `assertVisible: id: today-screen` — the assertion the other Today presets use
  — is intentionally **not** used for this preset: the underlying Today screen is
  correctly unreachable to accessibility while the modal is up, so the flow
  asserts the sheet's own visible content ("Granola bar") instead.

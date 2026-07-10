# FTY-323 visual verification

Simulator captures of the floating Today·Trends switcher (`FloatingSwitcher.tsx`)
proving the dark-mode separation fix and the capsule motion, taken against the
E2E debug build's `today.populated` visual-review preset (synthetic fixtures).

- `today-light.png` — Today, light mode. Unregressed: the pill reads as a
  distinct white/frosted capsule over the light canvas, as before.
- `today-dark.png` — Today, dark mode. The fix: the pill's fill and hairline
  border now visibly separate it from the `#1C1C1E` canvas (previously the
  fallback fill was near-identical to the canvas and the pill disappeared).
- `capsule-animation-today-to-trends.mov` — a short recording of tapping the
  Trends segment: the raised active capsule glides from Today to Trends with a
  short spring while navigation fires immediately (Trends screen mounts) and
  the pill itself does not shift position or size.
- `trends-dark-after-tap.png` — the settled end state right after the tap in
  the recording above: Trends is active, the capsule has moved under it, dark
  mode.

Captured via the `fatty://__visual-review?preset=today.populated&theme=...`
harness (see `mobile/e2e/visualReview/README.md`) on a leased headless
simulator, `today.populated`'s synthetic fixtures only.

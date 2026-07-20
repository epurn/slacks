# FTY-403 — Finer weigh-in cadence options via a menu/picker control

Running-app visual evidence for the weigh-in reminder cadence control.

## Capture setup

- **Device:** iPhone SE (3rd generation) — 375 pt, the smallest supported width
  (`docs/design/ux-design.md` §7 scopes SE → Pro Max), so this proves the
  criterion "each label rendered in full (no ellipsis) … at the smallest
  supported width".
- **How:** the app opened straight to Settings → PREFERENCES via the FTY-247
  visual-review deep link (`slacks://__visual-review?preset=settings.appearance`),
  then the "Weigh-in reminder" row was tapped to reveal the native menu. Light
  and dark captured with the simulator in the matching system appearance so the
  native action-sheet menu (which follows device appearance) renders in-theme.

## Evidence

| Criterion | Light | Dark |
| --- | --- | --- |
| Row shows the current cadence + native pop-up trigger | `fty403-cadence-row-light.png` | `fty403-cadence-row-dark.png` |
| Menu open — all seven cadences, full labels, no truncation | `fty403-cadence-menu-light.png` | `fty403-cadence-menu-dark.png` |

The menu is the platform-native `ActionSheetIOS` (not a hand-rolled pill group),
listing every option on its own full-width row, ordered most → least frequent
with `Off` last: **Daily · Every other day · Twice a week · Weekly · Every 2
weeks · Monthly · Off**. The closed row shows the current choice ("Weekly") with
the iOS up/down pop-up-button chevron.

The Maestro flow asserted `Every other day`, `Twice a week`, and `Every 2 weeks`
visible in the open menu on both themes before capturing each screenshot, so the
frames are of a genuinely-open, fully-populated menu.

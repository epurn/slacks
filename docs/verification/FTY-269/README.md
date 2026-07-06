# FTY-269 — iOS visual-review launch without the "Open in Fatty?" dialog: running-app evidence

Captured on a freshly **erased** iOS simulator (iPhone, iOS 26.5) — i.e. one that
has never opened the `fatty://` scheme before, the exact condition under which
iOS's one-time "Open in Fatty?" confirmation appears — against the E2E debug
build (`EXPO_PUBLIC_FATTY_E2E=true`), driving the committed
`mobile/.maestro/visual-review-smoke.yaml` entry point unmodified except for the
new `runFlow: common/accept-open-in-fatty.yaml` step FTY-269 adds after every
`openLink`.

## What changed

`mobile/.maestro/common/accept-open-in-fatty.yaml` is a new shared subflow:

```yaml
- extendedWaitUntil:
    visible:
      text: "Open in .Fatty.*"
    timeout: 10000
    optional: true
- runFlow:
    when:
      visible:
        text: "Open in .Fatty.*"
    commands:
      - tapOn:
          text: "Open"
```

The `extendedWaitUntil` waits (optionally, up to 10s) for the exact system alert
title, matched by the quote-agnostic, full-match-safe regex `Open in .Fatty.*`
(see "Root cause" below). Because the matcher now matches the real smart-quote
title, the wait resolves the instant the alert appears, and the `when:` gate that
follows sees it and taps the alert's own `Open` button — the gate is not racing a
late alert, and `text: "Open"` full-matches only the button, never the longer
title. Being `optional`, on Android (where this dialog never appears) or on an
iOS simulator that has already accepted it (a permanent per-simulator OS choice)
the title is absent, so the wait warns and the gate is skipped — nothing is
tapped and the subflow is a no-op. It never taps an app-owned control (the gate
only fires while the exact system title is visible) and never swallows a real
failure, since the next `extendedWaitUntil` on the preset's settled marker still
fails normally if a preset never loads.
`mobile/.maestro/visual-review-smoke.yaml` and
`mobile/.maestro/correction-visual-review-seam.yaml` (the two committed flows
that call `openLink` on the `fatty://` scheme) both run this step after every
`openLink`, with no `tapOn: Open` left as a manual/ad-hoc step anywhere.

## Root cause of the earlier bounce, and the fix

Maestro's `text:` matcher is a **full-match regex**, and iOS renders this alert's
title with **smart quotes**: `Open in “Fatty”?`. The earlier selector
`Open in "Fatty"` (straight quotes, no trailing `?`) therefore never matched the
real alert — so the wait always warned and the `when:` gate never fired,
leaving the dialog up on a cold simulator regardless of timing. Inspecting the
live accessibility hierarchy confirmed the title node's `accessibilityText` is
`Open in “Fatty”?` and the button's is exactly `Open`. The fixed selector
`Open in .Fatty.*` is quote-agnostic (`.` matches the smart *or* straight quote)
and full-match-safe (`.*` absorbs the trailing `?`), so it matches the real
system alert; the wait now resolves the instant the alert appears and the gate
taps the alert's own `Open` button.

## Proof the dialog is real and is handled without a manual tap

The simulator was erased (`xcrun simctl erase`) before this run specifically so
the "Open in Fatty?" confirmation would genuinely fire on the very first
`openLink` — proving the fix handles the real dialog, not a no-op on an
already-accepted device. The Maestro run log for the first preset:

```
Open fatty://__visual-review?preset=today.populated&theme=light... COMPLETED
Run common/accept-open-in-fatty.yaml...
  Assert that (Optional) "Open in .Fatty.*" is visible... COMPLETED
  Run flow when "Open in .Fatty.*" is visible...
    Tap on "Open"... COMPLETED
  Run flow when "Open in .Fatty.*" is visible... COMPLETED
Run common/accept-open-in-fatty.yaml... COMPLETED
Assert that id: visual-review-settled:today.populated is visible... COMPLETED
Assert that id: today-screen is visible... COMPLETED
Take screenshot today-populated-light... COMPLETED
```

The optional `extendedWaitUntil` **matched** the real alert and resolved on its
appearance, the `when:` gate saw it and tapped the alert's `Open` button, and the
preset then reached its settled marker — with **no manual/ad-hoc tap step**
anywhere in the committed flow. Every later preset's accept step reports the wait
`WARNED` and the gate `SKIPPED` (the dialog never reappears once accepted — a
permanent per-simulator OS choice), the expected no-op path:

```
Open fatty://__visual-review?preset=trends.populated&theme=dark... COMPLETED
Run common/accept-open-in-fatty.yaml...
  Assert that (Optional) "Open in .Fatty.*" is visible... WARNED
  Run flow when "Open in .Fatty.*" is visible...
  Run flow when "Open in .Fatty.*" is visible... SKIPPED
Run common/accept-open-in-fatty.yaml... COMPLETED
Assert that id: visual-review-settled:trends.populated is visible... COMPLETED
```

## Screenshots: every preset after the dialog reached its settled marker

All captured in the same Maestro run, immediately after the erased-simulator
dialog was auto-dismissed on the very first preset — no rebuild, no manual step.

| Screenshot | Preset | Proves |
|------------|--------|--------|
| `today-populated-light.png` | `today.populated` | The preset that had to clear the real "Open in Fatty?" dialog reaches its settled, populated state (245/2,000 kcal, Greek yogurt + Banana) with no manual tap |
| `trends-populated-dark.png` | `trends.populated` | Dialog-free launch continues across a preset switch (theme forced dark) |
| `today-empty-light.png` | `today.empty` | Runtime switch back to an empty-state preset, still dialog-free |
| `weight-sheet-light.png` | `weight.sheet` | The weight-log sheet sub-state (FTY-265) opens dialog-free |
| `today-signed-out-light.png` | `today.signed_out` | The signed-out sign-in surface opens dialog-free |
| `today-populated-after-signed-out-light.png` | `today.populated` (after signed_out) | The non-sticky signed-out regression guard still passes dialog-free |
| `settings-goal-edit-light.png` | `settings.goal_edit` | Settings sub-state seam (FTY-267) opens dialog-free |
| `settings-body-edit-light.png` | `settings.body_edit` | Settings sub-state seam (FTY-267) opens dialog-free |
| `settings-appearance-light.png` | `settings.appearance` | Settings sub-state seam (FTY-267) opens dialog-free |
| `today-confirm-parsed-light.png` | `today.confirm_parsed` | Today-owned sub-state seam (FTY-262) opens dialog-free |
| `correction-detail-light.png` | `correction.detail` | Correction sheet sub-state seam (FTY-263) opens dialog-free |

11 consecutive `openLink` calls (including the one that hit the real dialog)
reached their settled marker with zero manual dismissal steps in the committed
flow.

## Out-of-scope: `correction.typeahead` / `correction.confirm_apply` markers on iOS

The same run's next preset, `correction.typeahead`, fails its settled-marker
assertion on iOS — **this is pre-existing and unrelated to the dialog fix**. Per
`docs/verification/FTY-263/README.md`, that marker's load-bearing assertion runs
on Android in CI; the iOS platform is documented there as visual-evidence-only
because `NativeSheet`'s iOS presentation does not reliably expose in-modal
content to the accessibility tree the way the Android `Modal` fallback does. The
dialog itself was already accepted and never reappeared before this failure (see
the log above — every accept step after the first reports `WARNED`/no-op), so
this is not a regression introduced by FTY-269. See `planner_notes` on this
story's result for the out-of-scope note.

## Android `openLink` path (unchanged)

FTY-269 does not modify the `openLink` command itself, any preset/registry/
contract code, or `.github/workflows/mobile-e2e.yml`. The new accept step is
`optional: true` throughout, so on Android — where "Open in \"Fatty\"" never
renders — both its steps resolve to `WARNED`/no-op exactly like the
already-accepted-iOS-simulator case demonstrated above, and the flow proceeds
to the same `extendedWaitUntil` on the settled marker as before this change. No
Android emulator/`adb` tooling was available in this authoring environment to
run the flow directly; the retained `mobile-e2e` CI workflow (unchanged by this
diff) is the actual verification gate for the Android path per
`mobile/.maestro/README.md`'s "CI coverage" section.

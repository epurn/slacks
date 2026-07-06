# Visual-review mode (FTY-247)

Visual-review mode lets a tester or automated screenshot tooling open a **named
screen/state** directly in the E2E debug build — with synthetic data and a forced
light/dark theme — **without rebuilding the app** for each state, walking a live
backend, or hand-authoring temporary Maestro YAML.

It is an extension of the existing E2E launch harness (`../launchMode.ts`) and is
**only** active behind the same gate: a `__DEV__` build compiled with
`EXPO_PUBLIC_FATTY_E2E=true` (`isE2EMode()`). In a release build the entry point
is inert.

## Entry point

Open a deep link with the app's `fatty://` scheme:

```
fatty://__visual-review?preset=<name>&theme=light|dark
```

- `preset` — the named state to open (see the manifest below). An unknown or
  unregistered name **fails closed**: the route renders a deterministic
  `visual-review-error` marker and never falls through to a real screen with
  partially-seeded state.
- `theme` — optional. `light` or `dark` forces that appearance for the launch;
  any other value is ignored and the preset's own default (or the system scheme)
  applies.

Example (Maestro):

```yaml
- openLink: "fatty://__visual-review?preset=today.populated&theme=dark"
- runFlow: common/accept-open-in-fatty.yaml
- extendedWaitUntil:
    visible:
      id: "visual-review-settled:today.populated"
    timeout: 20000
- takeScreenshot: today-populated-dark
```

On iOS, `openLink` can surface a one-time system "Open in Fatty?" confirmation
the first time the app opens via its custom scheme on a given simulator (see
[`../../.maestro/README.md`](../../.maestro/README.md#ios-launch-no-manual-open-in-fatty-dismissal-fty-269)).
`runFlow: common/accept-open-in-fatty.yaml` (defined in `mobile/.maestro/`)
deterministically dismisses it if — and only if — it is on screen, so every
`openLink` call should be followed by that step. It is a no-op on Android and on
an iOS simulator that has already accepted the dialog, and it never masks a
preset that genuinely fails to reach its settled marker.

## Settled marker

Each preset exposes a stable marker once its state has fully settled —
navigation reached the target screen, its data loaded, the theme applied, and the
screen went network-quiet:

```
visual-review-settled:<preset>
```

Screenshot automation should wait for this marker (it is an accessibility
`testID`) before capturing, so it never grabs a mid-load frame. The marker is an
invisible 1×1, non-interactive view — it never shifts layout or blocks touches.

### Modal sub-states (FTY-270)

`VisualReviewSettleOverlay` renders its marker as a **sibling of the navigator
Stack**. That is unreachable for a sub-state presented as a React Native
`<Modal accessibilityViewIsModal>`: on iOS that flag isolates the modal's own
accessibility subtree from everything outside it, so while the modal is
presented Maestro/XCUITest cannot see the shared overlay's marker at all — it
still renders, but outside the reachable tree.

**Rule:** a modal-based seam must render its own
`visual-review-settled:<preset>` marker **inside the modal's own subtree**,
under the same canonical testID convention. Use the shared
`VisualReviewSettleMarker` component so the testID, the invisible/
non-interactive styling, and the network-quiet settle-timing rule never need
reimplementing:

```tsx
import { VisualReviewSettleMarker } from '@/e2e/visualReview';

function MySheet({ visible, e2ePresetName }: Props) {
  return (
    <Modal accessibilityViewIsModal visible={visible}>
      {/* ...sheet content... */}
      <VisualReviewSettleMarker preset={e2ePresetName} />
    </Modal>
  );
}
```

- `preset` is the active preset's name while this seam's sub-state is the one
  presented, or `null`/`undefined` otherwise — the marker renders nothing until
  its own preset is active.
- An optional `ready` prop (default `true`) adds a further readiness gate for a
  sub-state whose own async data must also settle (e.g. a search result list or
  a pre-seeded draft) before the state is truly done loading — the marker waits
  for both the shared network-quiet window and `ready`.
- The helper is gated the same way as the rest of this module: inert outside
  `isE2EMode()`, so it is dead code in release builds.

`VisualReviewSettleOverlay` itself is built on this same component (passed the
navigator-reachable preset name), so there is one marker source of truth for
both the non-modal and the modal case — extending the convention here never
means redefining it per screen.

## Preset manifest (in-scope, FTY-247)

These presets are reachable purely through public navigation, shared fixtures,
and shared session control — no screen-owned code:

| Preset             | Screen / state                                              | Theme param |
| ------------------ | ----------------------------------------------------------- | ----------- |
| `today.populated`  | Today with a resolved multi-item day and a counting hero    | any         |
| `today.empty`      | Today's calm empty-day invite (no entries, full budget)     | any         |
| `today.signed_out` | The signed-out sign-in surface (null session, non-sticky)   | any         |
| `trends.populated` | Trends with populated weight + adherence cards              | any         |
| `trends.empty`     | Trends with empty weight + adherence cards                  | any         |
| `weight.populated` | Trends weight card with a synthetic series                  | any         |
| `weight.empty`     | Trends weight card with no series (empty state)             | any         |
| `settings.list`    | The settings route's top-level list                         | any         |

All fixtures are the synthetic constants the E2E flows already use — no real
users, bodies, or logs.

Presets switch at runtime with no rebuild and in any order: activating a preset
remounts the session/navigator subtree and re-seeds from the active preset's
fixtures. In particular the session is a pure function of the active preset —
`today.signed_out` hydrates a null session, every other preset hydrates the
synthetic one — so opening a signed-in preset after `today.signed_out` reseeds
the session cleanly rather than leaving it signed out.

### Deferred sub-state presets

States that sit behind component-local sub-state (a sheet/mode/step opened only
by a press callback — e.g. the correction detail sheet, the weight-log sheet, the
onboarding steps) are **not** here. Reaching them needs a small E2E-only
initial-state seam in the screen's own code, which the per-screen seam stories
(FTY-262..268) add in their own lane. Until a seam story registers such a preset,
its name is unregistered and fails closed.

Most of these sub-states are presented as a `<Modal accessibilityViewIsModal>`,
so their settled marker also needs the in-modal-subtree rule above (see "Modal
sub-states"), not just the registration below.

## Registration API (the join contract for FTY-262..268)

A screen-owned module contributes a sub-state preset by calling
`registerVisualReviewPreset(...)` from its own lane — **without editing the shared
registry or the manifest in `presets.ts`**:

```ts
import { registerVisualReviewPreset } from '@/e2e/visualReview';

registerVisualReviewPreset({
  name: 'correction.detail',
  route: '/',
  settledPath: '/',
  // Optional: fixture overrides installed while the preset is active.
  responses: [
    { match: (ctx) => ctx.pathEnd.endsWith('/log-events/by-date'), body: [/* … */] },
  ],
  // The seam story also wires the screen to open its sub-state when this preset
  // is active — that hook lives in the screen's own module, not here.
});
```

The registry, deep-link parsing, theme override, settled-marker convention, the
fail-closed gate, and the smoke harness are all owned here; per-screen presets
plug into them.

## Running the smoke flow

`.maestro/visual-review-smoke.yaml` opens representative presets and waits for
their settled markers. It is the reusable launcher for the screen visual audits —
run it against an installed E2E debug build the same way as any other flow:

```sh
cd mobile
maestro test .maestro/visual-review-smoke.yaml
```

See `../../.maestro/README.md` for how to build and install the E2E debug binary.

## Security / privacy

- The whole flow is gated on `isE2EMode()` (`__DEV__` **and**
  `EXPO_PUBLIC_FATTY_E2E=true`). Release builds dead-code-eliminate the
  activation paths; the deep-link route is inert.
- No fixture session or mock API is installed outside the gate.
- Fixtures are synthetic only — no secrets, tokens, backend URLs, real bodies, or
  real logs.

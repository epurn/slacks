# FTY-383 — Today composer attaches images to a text log submission

Running-app visual evidence for the unified text+image submission
(`docs/contracts/log-event-images.md`). Captured on the iOS simulator
(iPhone, iOS 26.5) driving the real `TodayScreen` end-to-end via the hermetic
E2E dev-client build (`mobile/.maestro/image-submit.yaml`), in both appearances.
The Maestro flow passed every step and assertion in each theme; each screenshot
is a `takeScreenshot` from that passing run.

In E2E mode the attach chooser returns a hermetic fixture image instead of the
OS photo picker (Maestro cannot drive the out-of-process picker), and the mock
fetch routes the multipart create keyed on the typed text
(`mobile/e2e/imageSubmitFixtures.ts`). No live backend, no real camera.

## States (light + dark)

| File | Criterion it proves |
| --- | --- |
| `fty383-empty-composer.png` | The attach action (photo+ SF Symbol) is mounted and reachable on the real Today screen, alongside the existing scan / capture-label / Add actions. |
| `fty383-composer-with-thumbnail.png` | Typing "2 of these bars" + attaching a photo shows a thumbnail with a working remove (×) control **in place**; Add becomes active (at-least-one-surface). |
| `fty383-post-submit-pending.png` | Submitting posts one multipart create; the entry appears immediately as a **pending** row in place — no navigation, no layout jump — and the composer clears (text + thumbnail gone). |
| `fty383-resolved.png` | A pull-to-refresh resolves the entry with the **image-derived** result: "Protein bar · 380 kcal" (2 bars scaled from the label facts) with the label/photo source glyph, counted in the hero and macros. |

- `light/` — light appearance (`xcrun simctl ui … appearance light`).
- `dark/` — dark appearance; the ThemeProvider follows system appearance, so
  the same flow renders the dark palette.

Reduce Motion and VoiceOver: the thumbnail entrance degrades to an instant
appearance under Reduce Motion (`theme/motion` `useReduceMotion`), and the
attach action, each thumbnail, and each remove control carry explicit
accessibility labels ("Attach photo", "Attached photo N", "Remove photo N") —
covered by the component tests in
`mobile/components/today/TodayComposer.test.tsx` and
`mobile/components/today/useComposerImages.test.tsx`.

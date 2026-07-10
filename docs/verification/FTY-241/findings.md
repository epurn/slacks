# FTY-241 — End-of-Sweep Visual Audit: Capture (mobile)

Eyes-on rendering verification of the **Capture** surfaces after the
accent-as-text (FTY-207..212) and type-scale (FTY-213..217) mechanical sweeps.
Evidence only — **no product code changed**. Any defect is filed as a planner
note, not fixed here.

## How the evidence was captured

Captured on the iOS simulator (iPhone, iOS 26.5) against the E2E debug build
(`EXPO_PUBLIC_FATTY_E2E=true`), driving the **FTY-247 visual-review presets**
(FTY-268 owns the three `capture.*` sub-states) — each preset opened by deep
link and screenshotted only after its `visual-review-settled:<preset>` marker
appeared. No manual RC-backend walking, no live state mutation. Same running
binary + Metro across all six frames, theme forced by the `&theme=` param.

Entry point: `fatty://__visual-review?preset=<name>&theme=light|dark`

The reproduction flow used to capture these frames is committed alongside as
`capture-audit.yaml` (opens each of the three presets in both themes and waits
on the settled marker before each `takeScreenshot`).

**Sim camera caveat:** the simulator has no camera, so the barcode and label
surfaces are exercised through the E2E granted-permission fixture
(`e2eCameraPermissionsHook`, FTY-194). Their camera preview is an inherently
black full-screen cover — expected and sufficient per the story's Sim camera
caveat; the audit verifies the *chrome* rendered over that cover.

## State-by-state verdict

| State | Preset | Light | Dark | Verdict |
|-------|--------|-------|------|---------|
| Barcode scanner (granted) | `capture.barcode_granted` | `capture-barcode-granted-light.png` | `capture-barcode-granted-dark.png` | ✅ Pass |
| Label framing guidance | `capture.label_guidance` | `capture-label-guidance-light.png` | `capture-label-guidance-dark.png` | ✅ Pass |
| Confirm parsed values | `capture.confirm_parsed` | `capture-confirm-parsed-light.png` | `capture-confirm-parsed-dark.png` | ✅ Pass |

## Accent-as-text verification (WCAG AA)

Pixel colours sampled directly from the committed PNGs (sRGB → relative
luminance → WCAG contrast ratio). AA threshold for text is **4.5:1**.

- **Barcode scanner** and **label guidance** are full-screen camera covers with
  all-white chrome on black (torch, close, reticle/frame, guidance text, "Type
  it instead", shutter). These surfaces carry **no accent-as-text site** —
  nothing to regress — and white-on-black chrome is trivially AA. Camera covers
  are dark by nature (design §3 "The camera is a full-screen cover"), so they do
  not theme-adapt; that is correct, not a defect.
- **Confirm-parsed sheet** — the one Capture surface with accent chrome:

  | Element | Role | Light contrast | Dark contrast | Reads AA? |
  |---------|------|----------------|---------------|-----------|
  | "Not now" | accent **text** | **7.09:1** — colour `(146,64,14)` = `accentText` | **6.88:1** — colour `(245,166,35)` on surface `(44,44,46)` | ✅ (also AAA) |
  | "Looks right" | accent **fill** (button; text sits on the fill) | 7.13:1 | 8.39:1 | ✅ |
  | "Not yet counted" | muted badge | 5.99:1 | 6.30:1 | ✅ |

  The light-mode "Not now" colour `(146,64,14)` is the **darker `accentText`
  token**, provably distinct from the raw `accent` `(232,150,12)` that fills the
  "Looks right" button in the same frame. That is exactly the accent-as-text
  sweep outcome: text sites use `colors.accentText`, not `colors.accent`.

## Type-scale verification

All text on all six frames renders on the `typeScale` tokens with **no clipped,
wrapped, truncated, or visibly mis-sized text**:

- Camera guidance ("Point at a barcode", "Type it instead", "Fit the nutrition
  label inside the frame") — single line, crisp, correctly sized.
- Confirm sheet: title "Granola bar", provenance line "Label scan" (SF Symbol
  camera glyph, not an emoji — consistent with *No emoji as UI chrome*), helper
  copy "Check the parsed values before this counts toward today.", "1 bar",
  the "190 kcal" numeral, the "P 4g  C 29g  F 7g" macro line, and the
  "Adjust" / "Looks right" actions — all render at the expected scale with no
  regression versus the pre-sweep layout.

## Defects

**None.** Every accent-as-text site renders `accentText` and reads AA in both
themes; type-scale rendering is regression-free. No planner notes filed.

### Non-defect observation

In the two camera-cover frames the OS status bar is visible in the dark capture
but not the light one. This is a screenshot-timing artifact of the status-bar
overlay on the black camera modal (the identical surface shows the status bar
fine in the dark run) — not a Fatty chrome, accent, or type-scale rendering
issue, and outside this story's scope. Recorded here for completeness only; no
note filed.

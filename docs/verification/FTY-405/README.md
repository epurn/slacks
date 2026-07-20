# FTY-405 — User-configurable API server base URL in Settings

Running-app visual evidence for the Settings → ACCOUNT & SERVER server-address
editor.

## Capture setup

- **Device:** iPhone 17 Pro simulator (iOS 26.5), E2E debug build
  (`EXPO_PUBLIC_SLACKS_E2E=true`), JS served from this branch.
- **How:** `mobile/.maestro/server-url-fty405.yaml`, driven end to end — nothing
  below is a seeded or hand-posed state. The flow opens Settings with the editor
  already open via the FTY-247 visual-review deep link
  (`slacks://__visual-review?preset=settings.server_edit|settings.server_switch`),
  then **types** the addresses and **taps** the real buttons. Themes are forced
  with the deep link's `&theme=` parameter.
- Two presets back it: `settings.server_edit` leaves `/healthz` unmocked;
  `settings.server_switch` answers it like a live Slacks server so the whole
  switch runs with no backend.

## Evidence

| Criterion | Light | Dark |
| --- | --- | --- |
| Settings exposes an editable API base URL (row + open editor, prefilled with the live server) | `fty405-server-field-light.png` | `fty405-server-field-dark.png` |
| A malformed URL is rejected with clear, non-technical copy; the app stays usable and can revert to default | `fty405-server-invalid-light.png` | `fty405-server-invalid-dark.png` |
| A change is explicitly confirmed, stating the sign-out before it happens | `fty405-server-confirm-light.png` | `fty405-server-confirm-dark.png` |
| Confirming clears the session and routes to sign-in **for the new server** | `fty405-server-signin-light.png` | `fty405-server-signin-dark.png` |

## What each frame proves

- **field** — the Server row is a disclosure row showing the live base URL
  (`http://localhost:8000`, the E2E-seeded connection), and its editor is a
  native grouped edit card with the address prefilled, the honest "Changing your
  server signs you out" note, and three ≥44 pt actions: Use default / Cancel /
  Continue. "Use default" is the way back to the default address.
- **invalid** — `not a server` was typed and Continue tapped: the field takes the
  coral error border and "That doesn't look like a valid server address." renders
  in place. No navigation, no probe fired, the session untouched, and the card is
  still fully usable. The flow's `assertVisible` on that copy is load-bearing — a
  silently-accepted bad address fails the run here.
- **confirm** — after a successful `/healthz` probe of
  `https://newserver.example.com`, the card resolves in place to "…is reachable.
  Switching signs you out — sign in again on the new server." The switch is never
  implicit.
- **signin** — after tapping "Switch & sign out": the session is gone and the app
  is on sign-in **naming the new host** ("Signing in to newserver.example.com").
  That subtitle is read from the connected base URL, so it is the running-app
  proof that the app repointed *and* that the old server's token was dropped
  rather than carried across. This assertion is the flow's strongest gate — a
  switch that kept the old session, or kept targeting the old server, cannot
  produce this frame.

The order in which the session is dropped (sign out first, *then* the new base
URL goes live — so no request can carry the old token to the new host) is not
visible in a screenshot; it is asserted directly in
`mobile/components/SettingsScreen.server.test.tsx` ("confirming a change clears
the session first, repoints every API call, and routes to sign-in").

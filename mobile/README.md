# mobile

The Fatty mobile app: an Expo / React Native, iOS-first client. The **Today
shell** renders the user's real log events from the backend (FTY-031): it lists
today's events with accessible per-entry status and lets the user submit
natural-language input to create a new `pending` event. While any entry is still
non-terminal the timeline **auto-refreshes** it to its terminal status without a
manual refresh (FTY-032, the ADR-0002 polling mechanism); a manual refresh is
also provided.

A resolved food/exercise item under an entry is **correctable** (FTY-050):
tapping it opens the correction sheet where the user can correct calories,
macros, servings, and exercise burn. Each edit
sends one `PATCH` per field to the FTY-051 edit endpoint and re-renders the
**current** values the server returns — including the server-rescaled
calories/macros from a servings edit (the UI never computes the rescale). Edits
are optimistic and roll back on failure, and a corrected field carries an
accessible "edited" indicator (text, not color alone) that names the preserved
original estimate.

## Owns

- The Expo application shell and screens (starting with the Today screen).
- Natural-language entry affordance and structured, editable timeline UI.
- Client-side state, navigation logic, and accessibility-critical components.

## Stack

- **Expo** (SDK 56) with **Expo Router** for file-based routing.
- **TypeScript** in strict mode.
- **Jest** (`jest-expo`) for tests and **ESLint** (`eslint-config-expo`) for
  linting.

## Layout

```
app/                 file-based routes (Expo Router)
  _layout.tsx        root Stack + SafeAreaProvider
  index.tsx          the Today route ("/")
  profile.tsx        the profile capture route ("/profile")
api/                 typed clients for the backend (config, profile, logEvents,
                     derivedItems)
components/          presentational UI (TodayScreen, EntryRow, ItemTimelineRow,
                     StatusIcon, ProfileForm, ProfileScreen)
state/               local state + pure logic (today.ts, derivedItems.ts,
                     polling.ts, useScreenActive.ts, profile.ts, session.ts)
```

`api/logEvents.ts` is the typed client for the FTY-030 log-event create /
list-today API (the timeline's backend). `state/today.ts` holds the timeline's
pure presentation logic: the exhaustive status → glyph/label/accessibility
mapping over the FTY-030 status state machine, newest-first ordering, the
optimistic-event builder, and reconciliation of polled results. `state/polling.ts`
holds the poll stop condition (`hasPendingWork` over the non-terminal statuses)
and the fixed-interval timer hook; `state/useScreenActive.ts` is the foreground +
route-focus signal that pauses polling when the screen is backgrounded or
unfocused. New screens are added by dropping route files into `app/` without
restructuring the shell.

`api/derivedItems.ts` is the typed client for the FTY-051 derived-item edit API
(`PATCH …/derived-items/{type}/{id}`); `state/derivedItems.ts` holds the
correction presentation logic: the per-type editable field vocabulary,
current-vs-estimated reading, the edited indicator predicate, value formatting,
and the optimistic single-field apply (which never rescales locally).
`components/ItemTimelineRow.tsx` renders each resolved item in the timeline and
opens `components/CorrectionSheet.tsx` on press for correction. `TodayScreen`
seeds derived items from an injectable map keyed by event id and reconciles each
edit's server result back into it.

`state/profile.ts` owns the minimal-required-profile capture logic (FTY-021):
the field vocabulary, unit conversion to canonical units (metres, kilograms),
and nonjudgmental client-side validation. `api/profile.ts` is the typed client
for the FTY-020 profile read/write API. The capture flow persists for the
authenticated user; `state/session.ts` is the seam for the mobile sign-in flow
(a later story) that supplies the bearer token — until then the screen renders a
"sign in to save" state.

## Develop

```sh
npm install          # first time
npm run ios          # open the Today screen in the iOS simulator
```

## Root verification

A package opts into root `make verify` by adding an executable `verify.sh` at the
package root. This package's `verify.sh` installs the locked dependencies and
runs typecheck, lint, and tests:

```sh
npm run typecheck    # tsc --noEmit (strict)
npm run lint         # eslint
npm test             # jest
```

These also run from the repo root via `make verify` (and `make mobile`). See
[`docs/architecture/repo-layout.md`](../docs/architecture/repo-layout.md).

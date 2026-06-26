# mobile

The Fatty mobile app: an Expo / React Native, iOS-first client. The first slice
(FTY-013) is a **Today shell** rendered entirely from local mock state — no
networking, auth, or log-creation flows yet.

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
api/                 typed clients for the backend (config, profile)
components/          presentational UI (TodayScreen, EntryRow, StatusIcon,
                     ProfileForm, ProfileScreen)
state/               local state + pure logic (today.ts, profile.ts, session.ts)
```

`state/today.ts` holds the Today shell's mock data and selectors. Its shape is an
**internal placeholder, not a committed contract** — the real timeline DTOs
arrive with the logging-spine stories. New screens are added by dropping route
files into `app/` without restructuring the shell.

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

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
components/          presentational UI (TodayScreen, EntryRow, StatusIcon)
state/               local mock state + pure selectors (today.ts)
```

`state/today.ts` holds the Today shell's mock data and selectors. Its shape is an
**internal placeholder, not a committed contract** — the real timeline DTOs
arrive with the logging-spine stories. New screens are added by dropping route
files into `app/` without restructuring the shell.

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

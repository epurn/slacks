# mobile

The Fatty mobile app package area (Expo / React Native, iOS-first).

## Owns

- The Expo application shell and screens (starting with the Today screen).
- Natural-language entry affordance and structured, editable timeline UI.
- Client-side state, navigation logic, and accessibility-critical components.

This directory is an intentionally empty scaffold. The first mobile code arrives
in **FTY-013: Mobile App Skeleton**.

## Root verification

A package opts into root `make verify` by adding an executable `verify.sh` at the
package root. Until that script exists, the package is skipped cleanly so the
scaffold verifies from a fresh checkout. See
[`docs/architecture/repo-layout.md`](../docs/architecture/repo-layout.md).

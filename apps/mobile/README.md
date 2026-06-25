# Mobile

This package is the future home for Fatty's iOS-first Expo / React Native app.

## Ownership

- Path: `apps/mobile`
- Story: FTY-010 monorepo scaffold
- Owns mobile screens, navigation, client-side state, accessibility-critical
  components, API DTO usage, and mobile tests once those stories add behavior.

## Current State

No UI shell, Expo runtime, native configuration, credentials, or user data live
here yet. This placeholder keeps the mobile boundary predictable while later
stories introduce TypeScript and app tooling.

## Verification

Root `make verify` will call this package automatically after a package
`Makefile` with a `verify` target is introduced. Until then, the root scaffold
check validates that this ownership boundary exists.

## Security And Privacy

Future mobile code must avoid storing secrets in the app bundle, treat backend
responses as untrusted until validated by typed client boundaries, and keep the
iOS experience accessible and nonjudgmental.

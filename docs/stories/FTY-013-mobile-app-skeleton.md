---
id: FTY-013
state: ready_with_notes
primary_lane: mobile-core
touched_lanes:
  - contracts
risk: low
tags:
  - expo
  - ios
  - mobile
approved_dependencies:
  - expo
  - react
  - react-native
requires_context:
  - docs/stories/README.md
  - docs/architecture/system-overview.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - ios-first-ui
  - accessibility
  - verify-command
autonomous: true
---

# FTY-013: Mobile App Skeleton

## State

ready_with_notes

## Lane

mobile-core

## Dependencies

- FTY-010

## Outcome

Fatty has an Expo / React Native mobile shell that opens to a simple iOS-first Today screen using local mock state.

## Scope

- Add the mobile app package under the mobile area.
- Create a Today screen shell with natural-language entry affordance and empty/mock timeline state.
- Use neutral, nonjudgmental UI language.
- Add package checks and wire mobile verification into root verification where practical.
- Document how to run the app locally.

## Non-Goals

- API integration.
- Auth/profile setup.
- Camera, barcode, or nutrition label flows.
- Full navigation architecture beyond what the skeleton needs.
- Desktop packaging.

## Contracts

- Mobile package location.
- Today screen route or entrypoint.
- Root verification integration.

## Security / Privacy

Do not store real food logs, body data, API keys, provider keys, or personal examples in mock data. UI should avoid shame, jokes, or edgy copy.

## Acceptance Criteria

- Expo app starts locally with a documented command.
- First screen is a Today shell, not a marketing page.
- UI is iOS-first, accessible, and uses local mock state only.
- Root `make verify` includes available mobile checks or documents why they are not yet available.

## Verification

- Run `make verify`.
- Run package-specific mobile lint/type/test commands if added.

## Planning Notes

- Prefer the smallest Expo setup that supports iOS-first development.
- Web support is optional unless it comes naturally from the chosen Expo setup.

## Readiness Sanity Pass

- Product decision gaps: none for initial mobile shell.
- Cross-lane impact: establishes mobile package and Today surface for later profile/logging stories.
- Security/privacy risk: low; avoid personal mock data and unsafe local config.
- Verification path: `make verify` plus mobile package checks when available.
- Assumptions safe for autonomy: yes.

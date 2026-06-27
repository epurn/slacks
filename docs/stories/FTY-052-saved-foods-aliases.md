---
id: FTY-052
state: merged
primary_lane: backend-core
touched_lanes:
  - contracts
  - security-privacy
review_focus:
  - object-level-authz
  - migration-rollback
  - input-validation
  - normalized-match-determinism
risk: high
tags:
  - saved-foods
  - aliases
  - typeahead
  - api
  - contracts
approved_dependencies: []
requires_context:
  - docs/contracts/README.md
  - docs/architecture/system-overview.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-052: Saved Foods And Aliases (Backend)

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- FTY-051 (corrections/edit foundation — a saved food is created from a corrected item)
- FTY-042 (structured parse step — the derived items a save is drawn from)

## Outcome

A user can deliberately save a corrected food and reuse it later: an explicit
"save this food" endpoint persists the corrected nutrition as a user-owned
saved food plus an alias for the phrase they originally typed, and a typeahead
search endpoint returns that user's saved foods by normalized prefix/contains
match so the mobile client (FTY-053) can re-apply stored values without
re-estimating.

## Scope

- Add a migration for two new user-owned tables:
  - `saved_foods`: `user_id` FK with `ON DELETE CASCADE`, canonical name, the
    corrected nutrition snapshot (calories, macros, default serving size + unit),
    and a `source` field recording provenance (e.g. saved-from-correction).
  - `food_aliases`: `user_id`, alias text, and an FK to `saved_foods`
    (`ON DELETE CASCADE`). Stores the original phrase the user typed mapped to
    the saved food.
- Implement an explicit **save endpoint**: given a corrected derived item (from
  FTY-051) and the originating typed phrase, create one `saved_foods` row from
  the corrected values plus one `food_aliases` row mapping that phrase to the
  new saved food. Save is always deliberate and user-initiated.
- Implement a **typeahead search endpoint**: `GET` with a query string that
  returns the requesting user's saved foods whose canonical name or any alias
  matches the query by **normalized prefix/contains** (case-folded, whitespace-
  and diacritic-normalized). The response carries each saved food's stored
  nutrition values so the client can apply them directly.
- Enforce object-level authorization on every path: a user can only save under,
  search within, and read their own foods. Cross-user save or search fails
  closed (returns the user's own empty/forbidden result, never another user's
  data).
- Validate input (non-empty/length-bounded name, alias, and query; well-formed
  nutrition snapshot) with a clear, typed error shape.
- Define the matching/normalization rule as a documented, deterministic
  contract so it is testable and stable across clients.

## Non-Goals

- Fuzzy or semantic matching of any kind. v1 is exact/prefix/contains on
  normalized text only — explicitly excluded to keep matching deterministic.
- Auto-save or implicit save. Only deliberately-saved foods exist.
- Managing, renaming, or deleting saved foods and aliases (later story).
- The mobile UI for saving and for the typeahead picker (FTY-053).
- Changing the correction model or derived-item shape (owned by FTY-051/042).

## Contracts

- `saved_foods` and `food_aliases` table + DTO contracts (user ownership,
  canonical name, nutrition snapshot, source, alias→saved-food mapping).
- The **save request/response** DTO (corrected item + originating phrase in,
  the typed saved food out).
- The **typeahead search** DTO (request query string + paged/limited response
  shape carrying saved foods with their stored nutrition values), consumed by
  FTY-053.
- The normalized-match rule (case folding, whitespace/diacritic normalization,
  prefix/contains semantics) is a named contract clients rely on; no fuzzy or
  semantic step is part of it.

## Security / Privacy

`saved_foods` and `food_aliases` hold a user's personal nutrition data and the
free-text phrases they typed, both sensitive and strictly user-owned. Every
access path (save, search, any read) must enforce object-level authorization
proven by negative tests that fail closed; cross-user access must never return
another user's foods or aliases. Alias and query text must not be logged.
Retention follows the data-retention doc — saved foods and aliases are deleted
on account/user deletion, enforced here by `ON DELETE CASCADE` on `user_id`.
Rated high: new migrations, two contracts, object-level authz, and sensitive
nutrition data.

## Acceptance Criteria

- The save endpoint creates one `saved_foods` row from a corrected derived item
  and one `food_aliases` row mapping the originating typed phrase to it, and
  returns the typed saved food.
- The typeahead endpoint returns only the requesting user's saved foods whose
  name or alias matches the query by normalized prefix/contains, including the
  stored nutrition values in the response.
- Matching is normalized and deterministic; no fuzzy or semantic results are
  ever returned (proven by tests that near-but-non-matching strings are excluded).
- Cross-user save and cross-user search fail closed (negative authz tests); a
  user never sees or writes another user's saved food or alias.
- Input validation rejects empty/oversized name, alias, or query and malformed
  nutrition snapshots with a clear typed error shape.
- The `saved_foods` / `food_aliases` migration applies and rolls back; rows
  carry user ownership and cascade-delete with the user.
- `make verify` passes.

## Verification

- Run `make verify` (API + migration + authz tests).
- Apply and roll back the `saved_foods` / `food_aliases` migration in a test
  database; confirm `ON DELETE CASCADE` removes a user's saved foods and aliases.
- Save-endpoint tests: validation failure, auth failure, success (row + alias
  created), and error-shape.
- Search-endpoint tests: validation failure, auth failure, success, and
  error-shape.
- Search-match unit tests: normalized prefix/contains hits, case/diacritic/
  whitespace folding, and explicit non-matches proving no fuzzy/semantic match.
- Negative authorization tests for both endpoints: cross-user save and cross-user
  search fail closed.

## Planning Notes

- The exact normalization steps (case folding, Unicode/diacritic handling,
  whitespace collapsing) and whether match is prefix-only vs prefix+contains
  should be fixed in the contract and cited from code; conservative,
  deterministic defaults — non-blocking but warrant reviewer attention, hence
  ready_with_notes.
- A search result limit/pagination cap should be chosen and documented to keep
  the typeahead bounded.
- FTY-051 (corrections foundation) is the source of the corrected derived item a
  save is built from and is still a roadmap candidate without its own file; this
  story must land after FTY-051 defines the corrected-item shape. Sequencing
  dependency only — does not change this story's contract surface.

## Readiness Sanity Pass

- Product decision gaps: none blocking — save is explicit, matching is
  normalized prefix/contains with fuzzy/semantic explicitly excluded, and the
  two tables + two DTOs are resolved. Normalization specifics and result cap are
  documented implementation choices (notes).
- Cross-lane impact: owns the `saved_foods`/`food_aliases` and save/typeahead
  contracts consumed by mobile FTY-053; builds on corrected items from FTY-051
  and derived items from FTY-042.
- Security/privacy risk: high; sensitive user-owned nutrition and typed phrases,
  object-level authz on every path with negative fail-closed tests, cascade
  retention, no logging of alias/query text.
- Verification path: `make verify` + migration rollback + cascade check +
  match-unit tests + negative authz tests for both endpoints.
- Assumptions safe for autonomy: yes; scope excludes fuzzy matching, auto-save,
  management/deletion, and the mobile UI, and the matching rule is a documented
  deterministic contract.

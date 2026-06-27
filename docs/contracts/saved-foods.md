# Contract: Saved Foods + Aliases + Typeahead

## Purpose

Define how a user **deliberately saves** a corrected food (FTY-051) and later
**re-finds** it by typeahead (FTY-052), so the mobile client (FTY-053) can apply a
stored nutrition snapshot without re-estimating. It covers:

1. the **`saved_foods`** and **`food_aliases`** tables and their DTOs (user
   ownership, canonical name, corrected nutrition snapshot, source provenance, and
   the typed-phrase → saved-food alias mapping);
2. the **save endpoint** (`POST` a corrected snapshot + the originating phrase →
   the typed saved food);
3. the **typeahead search endpoint** (`GET` with a query → the user's saved foods
   whose name or any alias matches, carrying their stored nutrition);
4. the **normalized-match rule** — a named, deterministic case/diacritic/whitespace
   fold with exact prefix/contains semantics that clients rely on.

Out of scope: fuzzy or semantic matching of any kind; auto-save or implicit save;
renaming, deleting, or otherwise managing saved foods/aliases (a later story); the
mobile save/picker UI (FTY-053); and any change to the correction or derived-item
shape (owned by FTY-051/042).

## Owner

backend-core / contracts / security-privacy lane:
`backend/app/models/saved_foods.py`, `backend/app/schemas/saved_foods.py`,
`backend/app/services/saved_foods.py`, `backend/app/routers/saved_foods.py`,
`backend/app/normalization.py` (the match rule), `backend/app/enums.py`
(`SavedFoodSource`), `backend/alembic/` (`0009`).

## Version

1 (FTY-052).

## Inputs

### Save request — `SaveFoodRequest`

`POST /api/users/{user_id}/saved-foods`

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string (1–200, non-blank) | Canonical name to save under. |
| `phrase` | string (1–200, non-blank) | The original phrase the user typed; persisted as the saved food's first alias. |
| `nutrition` | `NutritionSnapshot` | The corrected per-serving nutrition (below). |

`NutritionSnapshot`:

| Field | Type | Meaning |
| --- | --- | --- |
| `calories` | number (finite, `0 ≤ x ≤ 100000`) | Energy (kcal) for one default serving. Required. |
| `protein_g` / `carbs_g` / `fat_g` | number \| null (finite, `0 ≤ x ≤ 100000`) | Macros (g) for one serving; nullable when a macro was not resolved. |
| `serving_size` | number (finite, `0 < x ≤ 100000`) | The default serving the snapshot describes. Required. |
| `serving_unit` | string (1–32, non-blank) | Unit of the serving (e.g. `serving`, `g`, `ml`). Required. |

`user_id` is a path parameter scoping ownership. The body forbids unknown keys; the
server sets `source` — it is **not** client-controlled in v1.

### Search request

`GET /api/users/{user_id}/saved-foods?q=<query>`

| Param | Type | Meaning |
| --- | --- | --- |
| `q` | string (1–200) | Typeahead query, matched against names and aliases by the normalized-match rule. Required. |

The result limit is a fixed server cap (no client-tunable page size in v1); see
Outputs.

## Outputs

### Saved food — `SavedFoodDTO`

Returned by save (`201`) and as each search result item:

`id`, `user_id`, `name`, `calories`, `protein_g`, `carbs_g`, `fat_g`,
`serving_size`, `serving_unit`, `source` (`SavedFoodSource`; v1
`saved_from_correction`), `created_at`, `updated_at`. The stored nutrition rides
along so the client applies it directly.

### Search response — `SavedFoodSearchResponse`

`{ "items": SavedFoodDTO[], "limit": number }`. `items` are the matching saved
foods, deduplicated, ordered deterministically by normalized name then `id`, and
capped at `limit` (default **20**, hard max **50**).

### `saved_foods` table

| Column | Meaning |
| --- | --- |
| `id` | PK. |
| `user_id` | Owner (FK `users.id`, `ON DELETE CASCADE`), indexed. |
| `name` | Canonical name as saved. |
| `name_normalized` | Normalized form of `name` for matching (indexed). |
| `calories` | Per-serving energy (kcal), non-null. |
| `protein_g` / `carbs_g` / `fat_g` | Per-serving macros (g), nullable. |
| `serving_size` / `serving_unit` | The default serving the snapshot describes. |
| `source` | Provenance (`SavedFoodSource`); v1 `saved_from_correction`. |
| `created_at` / `updated_at` | Timestamps. |

### `food_aliases` table

| Column | Meaning |
| --- | --- |
| `id` | PK. |
| `user_id` | Owner (FK `users.id`, `ON DELETE CASCADE`), indexed. |
| `saved_food_id` | Parent saved food (FK `saved_foods.id`, `ON DELETE CASCADE`), indexed. |
| `alias` | The original typed phrase. |
| `alias_normalized` | Normalized form of `alias` for matching (indexed). |
| `created_at` / `updated_at` | Timestamps. |

One save writes exactly one `saved_foods` row and one `food_aliases` row,
committed together.

### The normalized-match rule (deterministic)

`normalize_text` (`backend/app/normalization.py`) is applied identically to stored
names/aliases and to the search query, in order:

1. **Unicode NFKD** decomposition (also folds compatibility forms).
2. **Diacritic strip** — drop combining marks (category `Mn`): `café` → `cafe`.
3. **Case fold** — `str.casefold` (e.g. `ß` → `ss`).
4. **Whitespace collapse** — every whitespace run → one space; ends stripped.

A saved food **matches** a query when the normalized query is a literal
**substring** (contains, which subsumes prefix) of the saved food's
`name_normalized` **or** the `alias_normalized` of any of its aliases. There is
deliberately **no** fuzzy, phonetic, stemming, or semantic step — a near-miss
(typo, synonym, reordered or run-together tokens) never matches. A query that
normalizes to empty matches nothing.

## Validation

- **Non-blank, length-bounded text.** `name`/`phrase` (1–200), `serving_unit`
  (1–32), and `q` (1–200) are stripped and rejected when empty or oversized → `422`
  (request-boundary pydantic error shape).
- **Well-formed nutrition.** `calories`/`serving_size` required; all numbers
  finite; `calories`/macros `≥ 0`, `serving_size > 0`, each `≤ 100000` → `422`
  otherwise.
- **No unknown keys.** The save body forbids extra fields (e.g. a client-supplied
  `source`) → `422`.
- **Missing/empty query.** A missing or empty `q` → `422`.

## Authorization

Object-level, on **every** path, **failing closed**:

- The caller must own `{user_id}` (`current_user.id == user_id`). A cross-user save
  or search raises `SavedFoodForbidden`, rendered `404` — a non-owner never writes
  under, reads, nor searches another user's foods, and the collection's existence
  is never confirmed.
- Every query is additionally scoped to the owner (`user_id == owner`), so the
  result set can never include another user's rows.
- `saved_foods` and `food_aliases` are user-owned with `ON DELETE CASCADE` from
  `users`; `food_aliases` also cascades from its `saved_foods` parent.

## Privacy and Retention

- `saved_foods` and `food_aliases` hold personal nutrition data and the free-text
  phrases the user typed — sensitive and strictly user-owned.
- **No text logging.** Alias and query text are never written to logs.
- **Retention.** Saved foods and aliases are retained until the owning saved food
  (aliases), user, or account is deleted, enforced by `ON DELETE CASCADE` on
  `user_id` (and on `saved_food_id` for aliases), per
  `docs/security/data-retention.md`. Deleting a user removes all their saved foods
  and aliases.

## Errors

| Condition | Result |
| --- | --- |
| Cross-user save or search | `404` (no disclosure, no write). |
| Missing/invalid credentials | `401`. |
| Blank/oversized `name`, `phrase`, `serving_unit`, or `q` | `422`. |
| Malformed nutrition (missing/negative/non-finite/out-of-range) | `422`. |
| Unknown key in the save body | `422`. |
| Missing `q` | `422`. |

## Examples

```
POST /api/users/{me}/saved-foods
{ "name": "White Rice", "phrase": "my usual rice",
  "nutrition": { "calories": 200, "protein_g": 4, "carbs_g": 44, "fat_g": 0.4,
                 "serving_size": 1, "serving_unit": "serving" } }
→ 201 { "id": ..., "name": "White Rice", "calories": 200.0, ...,
        "source": "saved_from_correction" }   (+ alias "my usual rice")

GET /api/users/{me}/saved-foods?q=breast      # contains-match on "Chicken Breast"
→ 200 { "items": [ { "name": "Chicken Breast", "calories": ..., ... } ], "limit": 20 }

GET /api/users/{me}/saved-foods?q=chickne     # typo — no fuzzy match
→ 200 { "items": [], "limit": 20 }
```

Covered by `tests/test_saved_foods_api.py` (save/search endpoints, validation,
error shapes, cross-user fail-closed, no-log), `tests/test_saved_foods_matching.py`
(normalization + prefix/contains hits + explicit non-matches), and
`tests/test_saved_foods_migration.py` (apply/rollback, ownership, real cascade
delete).

## Migration / Compatibility

- The `0009` migration applies (`alembic upgrade head`) on top of the `0008`
  corrections schema and is fully reversible (`alembic downgrade 0008`), verified
  by an apply/rollback test against a throwaway database.
- Additive: two new tables; no prior table is altered.
- The `100000` sanity bounds, the contains (prefix-subsuming) match semantics, the
  NFKD + diacritic-strip + casefold + whitespace-collapse normalization, and the
  default-20 / max-50 search cap are documented v1 choices.

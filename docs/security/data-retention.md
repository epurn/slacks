# Data Retention

Retention defaults should minimize stored personal data while preserving user value.

## Initial Defaults

- Account data: retained until account deletion.
- Profile data: retained until edited or account deletion.
- Food and exercise logs: retained until user deletion or account deletion.
- Body weight entries: retained until user deletion or account deletion.
- Saved foods, recipes, aliases, and memories: retained until user deletion or account deletion.
- Nutrition label images (`log_attachments`, FTY-077): discard by default — an uploaded image is retained only while needed for extraction and discarded afterward unless the user explicitly saves it. An explicit save writes exactly one user-owned `log_attachments` row (the image bytes plus the content-type, byte size, and content hash needed to retrieve and delete it); the default flow persists no raw image. Uploads are size- and content-type limited and rejected fail-closed before storage. The row is `ON DELETE CASCADE` from both the user and the owning log event, so a saved image is removed on log-event, user, or account deletion. It never stores model output (that is `evidence_sources`).
- Raw OCR text: avoid long-term retention unless needed for evidence; prefer extracted facts plus source metadata.
- Fetched web pages: do not store raw pages by default; store source URL, fetched timestamp, content hash, and extracted facts.
- Estimation runs: store model/provider, schema version, tool names, source references, assumptions, validation errors, and sanitized traces.
- Derived parse candidates (`derived_food_items`, `derived_exercise_items`) and `clarification_questions`: user-owned derived data from a log event; retained until the owning log event, user, or account is deleted (`ON DELETE CASCADE`), same as the food/exercise logs they derive from. They hold parsed names/portions, the resolved calories/macros (food) or active calories (exercise), and clarifying questions only — no raw prompts and no model output beyond the schema-validated, sanitized fields.
- Evidence sources (`evidence_sources`): user-owned provenance for a resolved food item (FTY-044 generic foods; FTY-060 barcode/Open Food Facts) — the source reference (e.g. `usda_fdc:<fdcId>` or `open_food_facts:<barcode>`), content hash, fetch timestamp, and an extracted per-100g facts snapshot. Never a raw fetched page or raw provider response. Retained until the owning log event, user, or account is deleted (`ON DELETE CASCADE`).
- Cached source facts (`products`): global trusted-source nutrition facts (USDA FDC generic foods; Open Food Facts packaged products by barcode, FTY-060) with **no** user-specific data — the per-100g facts for a generic food or a given barcode are the same for everyone. Keyed by `(source, query_key)` with a dedicated indexed `barcode` column for the Open Food Facts source. Cached to avoid repeat external lookups (a repeat barcode scan makes no external call) and retained as global source facts (nothing user-specific to delete); the `evidence_sources` link to a product is `ON DELETE SET NULL`, so clearing the cache never removes user-owned evidence. The barcode sent to Open Food Facts carries no personal context, and no raw OFF response is stored.
- Saved foods (`saved_foods`) and aliases (`food_aliases`) (FTY-052): user-owned data created only by a deliberate, user-initiated save. `saved_foods` holds a corrected per-serving nutrition snapshot (calories, optional macros, default serving size + unit), a canonical name, a normalized name for matching, and a provenance `source`; `food_aliases` holds the free-text phrase the user originally typed (plus a normalized form) mapped to a saved food. Both are user-owned with `ON DELETE CASCADE` from the user, and `food_aliases` also cascades from its `saved_foods` parent, so a user's saved foods and aliases are removed on user/account deletion (and a saved food's aliases on its deletion). Retained until the owning saved food (aliases), user, or account is deleted. The typed alias text and the typeahead query text are sensitive free text and are never logged.
- Corrections (`corrections`) and derived-item estimated/original snapshot columns (FTY-051): user-owned audit data. Each `corrections` row records a single user override of a derived food/exercise item field (the changed field, old/new value in canonical units, and source); the `*_estimated` columns on `derived_food_items` / `derived_exercise_items` hold the immutable original estimate alongside the editable current value. The table is **append-only** — the application never updates or deletes a correction (an immutability guard rejects both) — but rows are still removed on user/account deletion through `ON DELETE CASCADE` from the user and the owning derived item. Retained until the owning derived item, log event, user, or account is deleted. Old/new values are never logged.
- Logs: short operational retention; no secrets or unnecessary personal data.

## Deletion Requirements

- Users must be able to delete entries, attachments, saved foods, recipes, aliases, memories, weight entries, and accounts.
- Deletion should remove or anonymize user-specific data from derived summaries.
- Global source facts may remain if they contain no user-specific data.

## PR Requirement

Any change that adds a new stored field, attachment, log, cache, provider trace, or memory type must document retention behavior.


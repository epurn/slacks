# Data Retention

Retention defaults should minimize stored personal data while preserving user value.

## Initial Defaults

- Account data: retained until account deletion.
- Profile data: retained until edited or account deletion.
- Food and exercise logs: retained until user deletion or account deletion. A log event may carry an optional, opaque client `idempotency_key` (FTY-096) used to dedup a safe-to-retry offline submit — stored verbatim on `log_events`, never parsed, never logged, and never returned to the client. It adds no new retention surface: it lives on the owning event and is removed with it by the existing `ON DELETE CASCADE` on user/account deletion.
- Body weight entries: retained until user deletion or account deletion.
- Saved foods, recipes, aliases, and memories: retained until user deletion or account deletion.
- Nutrition label images (`log_attachments`, FTY-077): discard by default — an uploaded image is retained only while needed for extraction and discarded afterward unless the user explicitly saves it. An explicit save writes exactly one user-owned `log_attachments` row (the image bytes plus the content-type, byte size, and content hash needed to retrieve and delete it); the default flow persists no raw image. Uploads are size- and content-type limited and rejected fail-closed before storage. The row is `ON DELETE CASCADE` from both the user and the owning log event, so a saved image is removed on log-event, user, or account deletion. It never stores model output (that is `evidence_sources`).
- Raw OCR text: avoid long-term retention unless needed for evidence; prefer extracted facts plus source metadata.
- Fetched web pages: do not store raw pages by default; store source URL, fetched timestamp, content hash, and extracted facts.
- Estimation runs: store model/provider, schema version, tool names, source references, assumptions, validation errors, and sanitized traces.
- Derived parse candidates (`derived_food_items`, `derived_exercise_items`) and `clarification_questions`: user-owned derived data from a log event; retained until the owning log event, user, or account is deleted (`ON DELETE CASCADE`), same as the food/exercise logs they derive from. They hold parsed names/portions, the resolved calories/macros (food) or active calories (exercise), and clarifying questions only — no raw prompts and no model output beyond the schema-validated, sanitized fields.
- Evidence sources (`evidence_sources`): user-owned provenance for a resolved food item (FTY-044 generic foods; FTY-060 barcode/Open Food Facts; FTY-061 user labels; FTY-062 official-source pages and model-prior estimates; FTY-166 reference-source pages; FTY-279 user-stated nutrition facts) — the source reference (e.g. `usda_fdc:<fdcId>`, `open_food_facts:<barcode>`, `official_source:<url>`, `reference_source:<url>`, `user_text:<content_hash>`, or `model_prior`), content hash, fetch timestamp, and an extracted nutrition-facts snapshot on its stated `basis` (`per_100g`/`per_100ml`/`per_serving`, or `as_logged` for a user-stated total — FTY-279). For a model-prior fallback (FTY-062/166) a nullable `assumptions` JSON column records why the fallback was used (and any density/serving assumptions), so the entry surfaces an explicit source status and stays user-editable; it holds no raw user text. A `user_text` record (FTY-279) stores only the extracted, validated facts and an optional per-field provenance map (which fields were user-stated vs. estimated vs. unknown); its `user_text:<content_hash>` reference and content hash are computed over those normalized facts, **never** the raw diary phrase — the raw entry text lives only on the owning `log_events` row and is never copied into the evidence layer, `assumptions`, or traces. An official-source or reference-source record stores the page **URL** only — never the raw fetched page — and no raw provider response is stored. Retained until the owning log event, user, or account is deleted (`ON DELETE CASCADE`).
- Cached source facts (`products`): global trusted-source nutrition facts (USDA FDC generic foods; Open Food Facts packaged products by barcode, FTY-060) with **no** user-specific data — the per-100g facts for a generic food or a given barcode are the same for everyone. Keyed by `(source, query_key)` with a dedicated indexed `barcode` column for the Open Food Facts source. Cached to avoid repeat external lookups (a repeat barcode scan makes no external call) and retained as global source facts (nothing user-specific to delete); the `evidence_sources` link to a product is `ON DELETE SET NULL`, so clearing the cache never removes user-owned evidence. The barcode sent to Open Food Facts carries no personal context, and no raw OFF response is stored.
- Saved foods (`saved_foods`) and aliases (`food_aliases`) (FTY-052): user-owned data created only by a deliberate, user-initiated save. `saved_foods` holds a corrected per-serving nutrition snapshot (calories, optional macros, default serving size + unit), a canonical name, a normalized name for matching, and a provenance `source`; `food_aliases` holds the free-text phrase the user originally typed (plus a normalized form) mapped to a saved food. Both are user-owned with `ON DELETE CASCADE` from the user, and `food_aliases` also cascades from its `saved_foods` parent, so a user's saved foods and aliases are removed on user/account deletion (and a saved food's aliases on its deletion). Retained until the owning saved food (aliases), user, or account is deleted. The typed alias text and the typeahead query text are sensitive free text and are never logged.
- Corrections (`corrections`) and derived-item estimated/original snapshot columns (FTY-051): user-owned audit data. Each `corrections` row records a single user override of a derived food/exercise item field (the changed field, old/new value in canonical units, and source); the `*_estimated` columns on `derived_food_items` / `derived_exercise_items` hold the immutable original estimate alongside the editable current value. The table is **append-only** — the application never updates or deletes a correction (an immutability guard rejects both) — but rows are still removed on user/account deletion through `ON DELETE CASCADE` from the user and the owning derived item. Retained until the owning derived item, log event, user, or account is deleted. Old/new values are never logged.
- Derived daily targets (`daily_targets`, FTY-022/FTY-094) and the manual target
  override fields (FTY-095): user-owned sensitive derived body data. Each row holds
  the deterministic calorie + macro derivation (with the `inputs`/`assumptions`
  snapshot) and, when the user manually overrides a target, the nullable
  `override_*_target_*` value(s) plus an `override_set_at` timestamp (a bare time
  stamp, no PII). An override persists across derived recomputes and is cleared
  only by an explicit reset or by deletion/replacement of the owning goal. Both
  tables are `ON DELETE CASCADE` from the user, and `daily_targets` also cascades
  from `goal_id`, so a user's targets and overrides are removed on goal, user, or
  account deletion. Retained until the owning goal is edited/replaced or the user/
  account is deleted. Target numbers are never logged (diagnostics use user/goal
  ids).
- Offline outbox (on-device, FTY-104; retention revised FTY-277): raw log text
  captured while the device is offline is queued in an owner-scoped file on the
  device (not on the server) until it drains to the log-events create endpoint on
  reconnect. The file is scoped to the **owner** — the normalized server URL *and*
  the user id — so the same user id on two different self-hosted servers has two
  separate queues that never share storage. It holds the owner's own `raw_text`
  plus a client `idempotency_key`, capture timestamp, and local sync state —
  sensitive personal data, never logged or sent to analytics, and it stores no
  bearer token or credential. **Sign-out no longer deletes the queue** (FTY-277):
  it is preserved on-device so a queued capture is not lost, and is *hidden* while
  signed out (removed from app state, never rendered) and can be loaded or drained
  only after the *same* server+user owner signs in again — never under another
  user or server. It is removed only when the queue drains empty (leaving no
  residue) or by an explicit, user-initiated destructive purge. Signing out still
  deletes the session credential from the keychain. A drained entry becomes a
  normal `log_events` row and follows the server-side retention above; the
  on-device copy adds no server retention surface.
- Appearance preference (on-device, FTY-102): the Light / Dark / System display
  choice is stored in a small per-device file (`fatty-app-settings.json`) via
  expo-file-system. It is a non-sensitive UI preference — no body data, no
  personal data — held only on the device, never sent to the server, and never
  logged. It adds no server-side retention surface; reinstalling the app clears it.
- Logs: short operational retention; no secrets or unnecessary personal data.

## Deletion Requirements

Users must be able to delete their own data at two levels — direct deletion of
individual items, and full account deletion. The data model is built for this:
user-owned rows are `ON DELETE CASCADE` from the user (and from their parent log
event where applicable), so deleting a user or a parent record removes the
dependent rows.

**Required — direct user-initiated deletion** of individual items:
- Food and exercise log entries (cascading to derived items, clarification questions, evidence sources, and corrections).
- Body weight entries.
- Saved foods, recipes, aliases, and portion memories.
- Attachments (nutrition label images).

**Required — account deletion**, cascading to all user-owned data (profile, logs,
entries, saved foods, memories, attachments, corrections, weight history,
evidence) and the user and auth identity.

As-built status: only body weight entries currently expose a deletion endpoint
(`DELETE /api/users/{user_id}/weight-entries/{entry_id}`, FTY-070). The remaining
direct-deletion endpoints and the account-deletion endpoint are required for
release but **not yet implemented**; the schema-level cascades above are already
in place to support them. By design there is no per-item `DELETE` for individual
`evidence_sources` or `clarification_questions` — they are removed only as cascade
consequences of deleting the parent log event, user, or account. Global source
facts (`products`, cached USDA/OFF data) remain after user deletion since they
contain no user-specific data.

- Deletion should remove or anonymize user-specific data from derived summaries.
- Global source facts may remain if they contain no user-specific data.

## PR Requirement

Any change that adds a new stored field, attachment, log, cache, provider trace, or memory type must document retention behavior.


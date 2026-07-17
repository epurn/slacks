# Data Retention

Retention defaults should minimize stored personal data while preserving user value.

## Initial Defaults

- Account data: retained until account deletion.
- Profile data: retained until edited or account deletion.
- Food and exercise logs: retained until user deletion or account deletion. A log event may carry an optional, opaque client `idempotency_key` (FTY-096) used to dedup a safe-to-retry offline submit — stored verbatim on `log_events`, never parsed, never logged, and never returned to the client. It adds no new retention surface: it lives on the owning event and is removed with it by the existing `ON DELETE CASCADE` on user/account deletion. A user-deleted log event (FTY-321) is a **soft void**, not a row deletion: a nullable, set-once `voided_at` timestamp on `log_events` (a bare timestamp, no PII, never logged) marks the event, the event row and its derived rows (derived items, clarification questions, evidence sources, corrections, saved label-image attachments) are retained in storage, and every read model excludes them (`docs/contracts/log-events.md`). The marker adds no new retention surface: it lives on the owning event and the retained rows are hard-removed only by the existing user/account-deletion cascades.
- Body weight entries: retained until user deletion or account deletion.
- Saved foods, recipes, aliases, and memories: retained until user deletion or account deletion.
- Nutrition label images (`log_attachments`, FTY-077): discard by default — an uploaded image is retained only while needed for extraction and discarded afterward unless the user explicitly saves it. An explicit save writes exactly one user-owned `log_attachments` row (the image bytes plus the content-type, byte size, and content hash needed to retrieve and delete it); the default flow persists no raw image. Uploads are size- and content-type limited and rejected fail-closed before storage. The row is `ON DELETE CASCADE` from both the user and the owning log event, so a saved image is hard-removed whenever either owning row is actually deleted (user or account deletion). The user-initiated log-event delete (FTY-321) is a **soft void**, not a row deletion — it does not fire the cascade, so a saved image on a voided event is retained (like the event's other derived rows) until the user/account-deletion cascades remove it. It never stores model output (that is `evidence_sources`).
- Mixed text+image submission images (`log_attachments` rows marked `transient`, FTY-374/FTY-375, migration `0022`): the **same retained-only-while-needed-for-extraction rule, reached via a transient DB row instead of an in-request buffer**, because the async estimation worker (ids-only job payload) must load the images by event id. Each validated image of a unified text+image log submission (`docs/contracts/log-event-images.md`) is persisted at create marked `transient` and **hard-deleted (purged) by the worker in the same transaction as the event's terminal estimation status** (`completed`/`failed`) — the one sanctioned application-level row deletion, since the row is a working buffer, not audit history. The rows are retained across an awaiting-answer clarification window (a re-estimate reloads them) and are also removed by the user/account/event-deletion cascades. A submission-level `save=true` writes ordinary saved rows (previous bullet) instead; with `save` absent/false no image survives estimation. A submission is capped at `MAX_SUBMISSION_IMAGES` (4) images, each fail-closed size/type/signature validated before any persistence. The image bytes go to the configured LLM/vision provider only — never search/fetch/other egress, never logs, never the queue, never estimation-run traces/errors.
- Raw OCR text: avoid long-term retention unless needed for evidence; prefer extracted facts plus source metadata.
- Fetched web pages: do not store raw pages by default; store source URL, fetched timestamp, content hash, and extracted facts.
- Estimation runs: store model/provider, schema version, tool names, source references, assumptions, validation errors, and sanitized traces. The trace's structured decision entries (FTY-255, `docs/contracts/estimation-jobs.md` "Decision trace") hold bounded sanitized labels, clamped counts, and non-secret source references only — an embedded URL keeps scheme/host/path with the query string, fragment, and userinfo dropped and its hostname labels and path segments secret-redacted; labels are control-character-stripped and redacted of secret-looking material; the entry count is capped per run. No raw event text, prompts, provider output, fetched pages, search snippets, or keys/tokens are ever stored; a global source row's bounded description may appear (global source data, not user data). The recorded provider/model are the configured selector and model string — operator configuration, not secrets. Runs remain user-tied rows and follow the owning log event's retention (`ON DELETE CASCADE`).
- Derived parse candidates (`derived_food_items`, `derived_exercise_items`) and `clarification_questions`: user-owned derived data from a log event; retained until the owning log event, user, or account is deleted (`ON DELETE CASCADE`), same as the food/exercise logs they derive from. They hold parsed names/portions, the resolved calories/macros (food) or active calories (exercise), and clarifying questions only — no raw prompts and no model output beyond the schema-validated, sanitized fields.
- Evidence sources (`evidence_sources`): user-owned provenance for a resolved food item (FTY-044 generic foods; FTY-060 barcode/Open Food Facts; FTY-061 user labels; FTY-062 official-source pages and model-prior estimates; FTY-166 reference-source pages; FTY-279 user-stated nutrition facts) — the source reference (e.g. `usda_fdc:<fdcId>`, `open_food_facts:<barcode>`, `official_source:<url>`, `reference_source:<url>`, `user_text:<content_hash>`, or `model_prior`), content hash, fetch timestamp, and an extracted nutrition-facts snapshot on its stated `basis` (`per_100g`/`per_100ml`/`per_serving`, or `as_logged` for a user-stated total — FTY-279). For FTY-252 count-serving named-food facts, source-backed official/reference rows keep the page URL/ref as provenance and persist only the resolved item totals plus the extracted fact snapshot; raw page text and raw provider output still are not stored. A model-prior count-serving fallback records only a content-free structured assumption such as `model_prior_count_serving:5 cracker`, never raw diary text. For a model-prior fallback (FTY-062/166) a nullable `assumptions` JSON column records why the fallback was used (and any density/serving assumptions), so the entry surfaces an explicit source status and stays user-editable; it holds no raw user text. A `user_text` record (FTY-279) stores only the extracted, validated facts and an optional per-field provenance map (which fields were user-stated vs. estimated vs. unknown); its `user_text:<content_hash>` reference and content hash are computed over those normalized facts, **never** the raw diary phrase — the raw entry text lives only on the owning `log_events` row and is never copied into the evidence layer, `assumptions`, or traces. When a `user_text` record's missing macros are filled by the comparable-reference aggregate fallback (FTY-281), that provenance is recorded in the same `user_text` row's `assumptions` and holds only: the machine-readable `comparable_reference` estimate-basis marker, a method line (which macros were estimated, the count of compatible references and outliers dropped, and the stated kcal they were scaled to), the compatibility summary (shared food form/ingredient terms), and, per contributing reference, its `reference_source:<url>` ref, a `sha256:` content hash of the extracted per-100g facts, and that per-100g nutrition snapshot. It never stores raw fetched page text, the raw diary phrase, or any user profile/goal/body-metric context (the search identity is deny-listed and bounded before egress). An official-source or reference-source record stores the page **URL** only — never the raw fetched page — and no raw provider response is stored. A record whose facts were transcribed from a search-result title+snippet rather than the fetched page (FTY-314) is marked only by the content-free `search_result_snippet` assumption label; the raw snippet and raw search JSON are never stored in the evidence layer, `assumptions`, traces, or logs. Retained until the owning log event, user, or account is deleted (`ON DELETE CASCADE`).
- Cached source facts (`products`): global trusted-source nutrition facts (USDA FDC generic foods; Open Food Facts packaged products by barcode, FTY-060) with **no** user-specific data — the per-100g facts for a generic food or a given barcode are the same for everyone. Keyed by `(source, query_key)` with a dedicated indexed `barcode` column for the Open Food Facts source. Cached to avoid repeat external lookups (a repeat barcode scan makes no external call) and retained as global source facts (nothing user-specific to delete); the `evidence_sources` link to a product is `ON DELETE SET NULL`, so clearing the cache never removes user-owned evidence. The barcode sent to Open Food Facts carries no personal context, and no raw OFF response is stored.
- Saved foods (`saved_foods`) and aliases (`food_aliases`) (FTY-052): user-owned data created only by a deliberate, user-initiated save. `saved_foods` holds a corrected per-serving nutrition snapshot (calories, optional macros, default serving size + unit), a canonical name, a normalized name for matching, and a provenance `source`; `food_aliases` holds the free-text phrase the user originally typed (plus a normalized form) mapped to a saved food. Both are user-owned with `ON DELETE CASCADE` from the user, and `food_aliases` also cascades from its `saved_foods` parent, so a user's saved foods and aliases are removed on user/account deletion (and a saved food's aliases on its deletion). Retained until the owning saved food (aliases), user, or account is deleted. The typed alias text and the typeahead query text are sensitive free text and are never logged.
- Corrections (`corrections`) and derived-item estimated/original snapshot columns (FTY-051): user-owned audit data. Each `corrections` row records a single user change to a derived food/exercise item field — a numeric override (the changed field, old/new value in canonical units, and source) or, since FTY-377, a display-name rename (`name_edit`: the prior/new name in the bounded `old_value_text` / `new_value_text` columns); the `*_estimated` columns on `derived_food_items` / `derived_exercise_items` hold the immutable original estimate alongside the editable current value. The table is **append-only** — the application never updates or deletes a correction (an immutability guard rejects both) — but rows are still removed on user/account deletion through `ON DELETE CASCADE` from the user and the owning derived item. Retained until the owning derived item, log event, user, or account is deleted. Old/new values — numbers and item names alike — are never logged, and a rejected rename never echoes the submitted name.
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
  choice is stored in a small per-device file (`slacks-app-settings.json`) via
  expo-file-system. It is a non-sensitive UI preference — no body data, no
  personal data — held only on the device, never sent to the server, and never
  logged. It adds no server-side retention surface; reinstalling the app clears it.
- Exact-evidence proposal reference (`Make it exact`, FTY-306/FTY-307): **stateless,
  not stored.** A proposal is not persisted in any table; the client receives an
  opaque, server-signed `proposal_ref` — an HMAC-SHA256 signature (keyed by the
  existing `SLACKS_AUTH_SECRET`) over a base64url JSON payload that binds the owning
  user, target item, evidence kind/quality, source type/ref, the extracted per-100g
  facts + basis, the default-serving costability metadata, and an issued/expiry pair
  (the replay guard). It carries **only** extracted/validated facts and refs — never
  raw image bytes, OCR text, raw provider output, or fetched page content — and is
  short-lived (an unapplied reference expires, default 30 minutes; it is not durable
  user history). Because nothing is stored server-side it adds **no** new retention
  surface: there is no proposal row to delete, and the signing secret is never
  embedded in the reference or logged. The nutrition values it carries and the
  reference itself are never logged, exactly as the correction/evidence values are
  not (mirrors the stateless bearer token, `app/security/tokens.py`).
- Logs: short operational retention; no secrets or unnecessary personal data.

## Deletion Requirements

Users must be able to delete their own data at two levels — direct deletion of
individual items, and full account deletion. The data model is built for this:
user-owned rows are `ON DELETE CASCADE` from the user (and from their parent log
event where applicable), so deleting a user or a parent record removes the
dependent rows.

**Required — direct user-initiated deletion** of individual items:
- Food and exercise log entries — delivered as a soft void (FTY-321): the entry and its derived items, clarification questions, evidence sources, corrections, and saved label-image attachments are excluded from every read but retained in storage until the user/account-deletion cascades remove them (see the as-built status below).
- Body weight entries.
- Saved foods, recipes, aliases, and portion memories.
- Attachments (nutrition label images).

**Required — account deletion**, cascading to all user-owned data (profile, logs,
entries, saved foods, memories, attachments, corrections, weight history,
evidence) and the user and auth identity.

As-built status: body weight entries expose a hard-deletion endpoint
(`DELETE /api/users/{user_id}/weight-entries/{entry_id}`, FTY-070), and food and
exercise log entries expose a user-initiated delete
(`DELETE /api/users/{user_id}/log-events/{event_id}`, FTY-321) implemented as a
**soft void**: it sets the set-once `voided_at` marker and excludes the event
and all its derived rows (derived items, clarification questions, evidence
sources, corrections, saved label-image attachments) from every read model —
including derived summaries — but
retains the rows in storage, consistent with append-only storage; the retained
rows are hard-removed only through the user/account-deletion cascades. The
remaining direct-deletion endpoints and the account-deletion endpoint are
required for release but **not yet implemented**; the schema-level cascades
above are already in place to support them. By design there is no per-item `DELETE` for individual
`evidence_sources` or `clarification_questions` — they are removed only as cascade
consequences of deleting the parent log event, user, or account. Global source
facts (`products`, cached USDA/OFF data) remain after user deletion since they
contain no user-specific data.

- Deletion should remove or anonymize user-specific data from derived summaries.
- Global source facts may remain if they contain no user-specific data.

## PR Requirement

Any change that adds a new stored field, attachment, log, cache, provider trace, or memory type must document retention behavior.

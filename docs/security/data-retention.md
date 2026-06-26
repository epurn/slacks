# Data Retention

Retention defaults should minimize stored personal data while preserving user value.

## Initial Defaults

- Account data: retained until account deletion.
- Profile data: retained until edited or account deletion.
- Food and exercise logs: retained until user deletion or account deletion.
- Body weight entries: retained until user deletion or account deletion.
- Saved foods, recipes, aliases, and memories: retained until user deletion or account deletion.
- Nutrition label images: retain only while needed for extraction unless the user explicitly saves the attachment.
- Raw OCR text: avoid long-term retention unless needed for evidence; prefer extracted facts plus source metadata.
- Fetched web pages: do not store raw pages by default; store source URL, fetched timestamp, content hash, and extracted facts.
- Estimation runs: store model/provider, schema version, tool names, source references, assumptions, validation errors, and sanitized traces.
- Derived parse candidates (`derived_food_items`, `derived_exercise_items`) and `clarification_questions`: user-owned derived data from a log event; retained until the owning log event, user, or account is deleted (`ON DELETE CASCADE`), same as the food/exercise logs they derive from. They hold parsed names/portions and clarifying questions only — no raw prompts and no model output beyond the schema-validated, sanitized fields.
- Logs: short operational retention; no secrets or unnecessary personal data.

## Deletion Requirements

- Users must be able to delete entries, attachments, saved foods, recipes, aliases, memories, weight entries, and accounts.
- Deletion should remove or anonymize user-specific data from derived summaries.
- Global source facts may remain if they contain no user-specific data.

## PR Requirement

Any change that adds a new stored field, attachment, log, cache, provider trace, or memory type must document retention behavior.


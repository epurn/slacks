# Contract: Interpretation Session

## Purpose

Define the **LLM-owned interpretation session** that spans a natural-language
estimation run — the global semantics FTY-324 introduced. One logical
`InterpretationSession` owns interpretation of the user's raw text plus accumulated
clarification answers end to end, across parse, food resolution, exercise
resolution, and evidence lookup. The parsed candidate set is the model's
**revisable hypothesis**, evidence tiers are **bounded tools** the loop may call,
and deterministic code retains authority over math, bounds, source acceptance
gates, egress, provenance, privacy, persistence, and fail-closed behavior.

This page is the single home for the session/hypothesis contract that the parse,
food-resolution, and evidence-retrieval contracts each consume:

- [parse-candidates.md](parse-candidates.md) owns the parse schema, sampling, and
  the initial hypothesis it routes.
- [food-resolution.md](food-resolution.md) owns the concrete per-tier evidence
  tools, routing, and serving math the loop drives.
- [evidence-retrieval.md](evidence-retrieval.md) owns the source hierarchy,
  lookup statuses, normalized fact schema, and retention/provider boundaries.
- [estimator-policy.md](estimator-policy.md) owns the FTY-298 clarification modes
  the loop's clarification boundary evaluates.

## Owner

estimator / contracts / backend-core lane:
`backend/app/estimator/` (the interpreter core FTY-325/FTY-326 implement against
this target), `backend/app/schemas/parse.py`, and the sibling contract docs above.
The `InterpretationSession` and `InterpretationHypothesis` are **run-local**
working objects — not public HTTP DTOs and not persisted wholesale.

## Version

2 (FTY-374, contract only): the session gains **image evidence surfaces**. An
event created by the unified text+image submission (`log-events.md` v9) enters
the session with its validated images available alongside the raw text at every
model-consultable interpretation call: text supplies identity/count/context, an
image supplies label facts as `user_label`-tier evidence (`parse-candidates.md`
v12, `estimation-jobs.md` v6). The images live inside the **same boundary as
the raw text** — the configured LLM/vision provider only, never
search/fetch/tool egress, never traces/logs — and image-derived output crosses
the same schema-validation trust boundary before deterministic code uses it.
No hypothesis-shape, trace-label, or decision-point vocabulary change; FTY-376
implements.

1 (FTY-348, contract only): extracts the FTY-324 interpretation-session and
hypothesis-revision semantics verbatim from `parse-candidates.md`,
`food-resolution.md`, `evidence-retrieval.md`, and `estimator-policy.md` into this
dedicated page. No normative change: FTY-324 defined the contract (the model owns
the revisable hypothesis; deterministic code owns math, bounds, provenance,
privacy, and persistence; evidence tiers are tools of the interpretation loop; raw
diary text stays inside the configured LLM boundary only), and FTY-325/FTY-326
implement it. No schema, persistence, provider, prompt, settings, API, migration,
or estimator behavior changes.

## The interpretation session

The natural-language estimation run has one logical **`InterpretationSession`**.
It begins with the raw log text and any accumulated `clarification_answers`, then
continues through parse, food resolution, exercise resolution, and evidence
lookup until the event reaches a terminal status. The session contract is:

> The model owns interpretation of the user's text end to end. Structured
> candidates are the model's working hypothesis — revisable whenever new evidence
> arrives — never a frozen upstream truth. Deterministic code owns math, bounds,
> provenance, privacy, and persistence. It never guesses intent, and it never
> discards or overrides user-stated detail because that detail did not fit an
> extracted field.

The raw log text and answered clarification text remain available **only inside
the configured LLM boundary** for every model interpretation call in the session.
They are not copied into search queries, fetch requests, run traces,
`assumptions`, `source_refs`, provider error strings, logs, or evidence rows.
The event's **image attachments** (FTY-374, `log-events.md` v9) are an evidence
surface with the same boundary: available to every model interpretation call in
the session (as `ImageInput`s via the vision-capable provider —
`estimation-jobs.md` v6), and never sent to search/fetch/tools, never logged,
never copied — as bytes, paths, or hashes — into traces, `assumptions`,
`source_refs`, or error strings. Facts a model reads off an image are trusted
only after schema validation, and persist as `user_label` evidence rows whose
`content_hash` provenance lives in `evidence_sources` (`parse-candidates.md`
v12).
Downstream search/fetch/model-prior tools receive the least-sensitive structured
inputs their contracts allow: sanitized item identity, bounded amount/unit fields,
source refs, fetched inert text, snippets, and content-free source-status labels.

## Interpretation hypothesis

An `InterpretationHypothesis` is a run-local working object. It is not a new public
HTTP DTO and is not persisted wholesale. It carries enough structure for
deterministic code to validate and calculate without interpreting intent:

| Field | Meaning |
| --- | --- |
| `session_id` | Run-local identifier used only inside the estimation run; never exposed as user data. |
| `raw_text` | The owning event's raw text, available to the configured LLM provider only. |
| `clarification_answers` | Prior answered question/answer pairs, fed to the model as bounded structured detail. |
| `items` | Ordered food/exercise hypothesis items. Each item has a run-local `hypothesis_item_id`, `type`, `name`, `quantity_text`, optional `unit`, `amount`, `barcode`, `brand`, and optional `stated_*` facts. |
| `item_links` | Run-local split/merge lineage between hypothesis items; used for traceability only, never as persisted user-visible data. |
| `evidence_view` | Bounded evidence gathered so far: source tier, lookup status, source refs, snippets/page extraction status, compatibility result, and content-free reject reason. Its records never carry raw fetched pages, raw snippets, provider output, or raw search queries. Separately from those records, a re-interpretation prompt may transiently include an unaccepted read's own bounded, FTY-314-framed page/snippet text drawn from the current fetch/snippet result at prompt-construction time (FTY-326) — model boundary only, never persisted, traced, or used for a search query or fetch URL. |
| `policy_view` | Active FTY-298 mode plus calibrated self-consistency/agreement signal metadata from ADR-0003. |
| `pending_questions` | Candidate clarification questions with item scope when an item-scoped question is allowed by FTY-278. |

The hypothesis may be revised during the same session. A revision may:

- add an item the initial parse missed;
- split one item into several items;
- merge duplicate or over-split items;
- remove a spurious item;
- correct an item identity, brand/product identity, amount, unit, or exercise
  detail;
- attach, detach, or correct a user-stated nutrition fact;
- mark an item as genuinely indeterminate for an allowed clarification reason.

## Model-consultable decision points

The following **model-consultable decision points** must be able to pass the raw
text, clarification answers, current hypothesis, and evidence view back to the
model for interpretation rather than relying only on frozen extracted fields:

| Decision point | Trigger |
| --- | --- |
| `initial_parse` | First structured interpretation of the raw log text. |
| `provider_clarification_adjudication` | A provider returns `needs_clarification`, samples disagree, or the hybrid score is conservative but a recognizable identity may be recoverable under FTY-298. |
| `source_selection` | Choosing which evidence tier(s) and query variants are applicable to an item. |
| `source_acceptance` | A source result, snippet, page extraction, barcode/OFF result, USDA row, official page, reference page, or model-prior estimate may or may not match the item the user meant. |
| `source_rejection_feedback` | A lookup misses, fetch fails, extraction is unresolved/low-confidence, compatibility rejects a result, or serving math rejects otherwise useful evidence. |
| `hypothesis_repair` | Evidence implies the initial item set was degenerate, over-split, under-split, brandless, amountless, or attached to the wrong item. |
| `clarification_boundary` | The session may ask only after the interpretation loop concludes the remaining item is genuinely indeterminate under the active FTY-298 mode, except deterministic gates that independently clarify/fail closed. |
| `answer_reestimate` | A clarification answer re-opens interpretation with the original raw text plus accumulated answers. |

Any current or future resolution decision that keys on a frozen extracted field
(`has_brand`, `amount_kind`, `name`, `unit`, `brand`, `quantity_text`, or a count
serving relation) must treat that field as a hypothesis feature, not authority.
It may be used by deterministic validators and as sanitized input to tools, but
if evidence suggests the feature is wrong or incomplete, the session revises the
hypothesis instead of forcing all later tiers to chase the stale value.

Confidence remains an engineered signal. The model may produce a verbalized
`confidence` because the existing schema carries it, but routing never trusts a
single self-reported score. Parse abstention uses the ADR-0003 hybrid
self-consistency/agreement signal and calibrated threshold, with FTY-298 mode
semantics layered on top; later interpretation calls that need uncertainty must
use the same cold-pass/agreement style or a stricter deterministic validator, not
a raw provider confidence claim.

## Evidence tiers as interpretation tools

The evidence tiers are **tools** the interpretation loop may call in a bounded
order, with deterministic code enforcing the caps and preconditions for each call.
The normative division of labour is:

- **Model-owned interpretation:** decide which source tier/tool is applicable,
  decide whether evidence describes the item the user meant, revise item
  identities/brands/amounts/splits/merges when evidence contradicts the current
  hypothesis, and conclude "genuinely indeterminate" only after the allowed
  FTY-298 policy path is exhausted.
- **Deterministic-owned execution:** enforce source enablement and egress
  boundaries, `sanitize_query`, allowlists, public-IP/HTTPS/fetch caps, provider
  retry/budget caps, schema validation, nutrition plausibility validators,
  brand/product compatibility checks that bound evidence acceptance, serving and
  count-scaling math, as-logged/user-text validation, provenance labels, object
  ownership, retention, and persistence.

Tier order remains evidence-first: source-backed evidence is tried before pure
model prior whenever an applicable provider is configured and available. FTY-324
changes **who may reinterpret** between tiers, not the privacy or safety posture.
A non-success lookup status, rejected compatibility check, fetch/extraction
failure, unusable serving basis, or snippet-only success feeds back into
interpretation as a bounded sanitized evidence-view record. It does not authorize
raw text egress, provenance-free averaging, source-order bypass, or model-prior
finalization while an applicable source remains usable. Deterministic code still
owns every lookup status, egress/fetch gate, fact-schema validation, serving math,
budget cap, and persisted provenance field; the model may only interpret which
bounded tool result describes the user's item.

The concrete per-tier tool table, the food re-interpretation trigger points, and
the deterministic tool-budget/fail-closed gates for food resolution live in
[food-resolution.md](food-resolution.md) (**Interpretation loop and evidence
tools**). The source hierarchy, lookup-status vocabulary, normalized fact schema,
and retention/provider boundaries the tools obey live in
[evidence-retrieval.md](evidence-retrieval.md).

## Deterministic-code authority and fail-closed gates

The interpretation loop never relaxes the deterministic authority. Implementations
of the session must keep the existing gates intact:

- bounded candidate count, query-variant count, search-result count, fetch size,
  timeout, content-type, retry, parse-repair, and trace-entry caps;
- all network egress through the configured search/fetch adapters only;
- no open-ended browser, crawling, filesystem, shell, email, calendar, or broad
  personal tools in the estimator;
- source/fact validation and serving math before persistence;
- rough estimates marked with rough/model/default/reference provenance and kept
  editable;
- deterministic plausibility, contradiction, abuse, schema, and egress gates may
  clarify or fail closed on their own authority, even if the model would prefer to
  estimate.

## Clarification boundary (FTY-298 modes, FTY-278 item-scoped)

The active clarification mode is evaluated **inside** the `InterpretationSession`,
whose current candidate set is a revisable hypothesis rather than frozen parse
output. For a recognizable item, "genuinely indeterminate" is an
interpretation-loop conclusion made with the raw text, accumulated clarification
answers, current hypothesis, and gathered evidence statuses in view. It is not a
deterministic shortcut from one missing field such as `has_brand = false`,
`amount_kind = missing`, a generic `name`, or an unrecognized `unit`. The mode
names, defaults, allowed last-resort clarification reasons, and rough-provenance
requirements are owned by [estimator-policy.md](estimator-policy.md).

This does **not** relax fail-closed behavior. Deterministic schema validation,
plausibility validators, contradiction checks, source/fetch policy gates, abuse
caps, serving-math failures under modes that allow asking, and provider/tool
unavailability may still raise clarification or failure according to their step
contracts.

When a mixed multi-item entry contains both costable and still-indeterminate
components, the required output shape remains **FTY-278 item-scoped partial
resolution**: resolved siblings are committed and counted, while each remaining
allowed question belongs to its specific unresolved component. FTY-324 does not
reopen that contract.

## Sanitized hypothesis-revision trace labels

Hypothesis revisions are traced with content-free labels. A trace entry for this
contract uses `decision = hypothesis_revision`; `candidate_index`, `tier`,
`amount_kind`, `has_brand`, and `result_count` may be included when useful, but
the entry must never include raw diary text, raw clarification answers, item
names, quantity phrases, prompts, provider output, fetched page/snippet text,
search queries, URLs with secrets, request/response bodies, or provider error
bodies.

Allowed `outcome` labels are:

- `initial_hypothesis`;
- `hypothesis_kept`;
- `item_added`;
- `item_removed`;
- `item_split`;
- `item_merged`;
- `identity_revised`;
- `brand_revised`;
- `quantity_revised`;
- `unit_revised`;
- `stated_nutrition_revised`;
- `exercise_detail_revised`;
- `evidence_attached`;
- `evidence_rejected`;
- `clarification_needed`;
- `deterministic_gate_failed`;
- `revision_truncated`.

The labels describe only the kind of revision. The revised values live in the
ordinary user-owned derived-item/evidence rows after validation and persistence,
not in the run trace.

## Privacy and Retention

The privacy boundary is exact and must not be weakened by the interpretation loop:

- **Raw text stays inside the model boundary.** The raw log text and accumulated
  clarification answers may be sent to the configured LLM provider for
  interpretation throughout the `InterpretationSession`, as the parse step already
  does today. They must not be sent to search/fetch providers or copied into run
  traces, source refs, assumptions, diagnostics, error strings, or logs; those
  surfaces keep the sanitized label/source-id vocabulary described above.
- **Tools receive sanitized inputs only.** Search queries are sanitized item
  identity only; fetch requests are selected URLs only; traces, assumptions,
  source refs, errors, and logs carry only bounded sanitized labels, source ids,
  and safe source refs. Source misses/rejections feed re-interpretation as
  bounded evidence-view records, never as raw user text. An unaccepted
  page/snippet read may additionally hand its own bounded, FTY-314-framed inert
  text to the re-interpretation prompt transiently (FTY-326) — the same LLM
  boundary that already reads that text for extraction; it stays out of every
  trace/ledger/persisted surface and is never used to build a query or fetch.
- **No provenance dishonesty.** Rough estimates carry rough/model/default/reference
  provenance and stay editable; source-backed values keep their source provenance.
  The loop never presents a rough estimate as a trusted value and never averages
  sources without compatibility checks, source refs, and rough-estimate provenance.
- **Retention follows the owning event.** Derived items, evidence sources, and
  clarification questions live until the owning event, user, or account is deleted;
  no raw page, prompt, or provider output is retained
  (`docs/security/data-retention.md`).

## Migration / Compatibility

- **FTY-374 (contract only; no code or migration in this story).** Adds the
  image evidence surface: a unified text+image submission's validated images
  are available to the session's model interpretation calls under the same
  boundary as the raw text (provider-only, never tool egress or
  traces/logs). No `InterpretationHypothesis` field, decision-point, or
  trace-label vocabulary changes; the existing `evidence_view` sanitized
  record shapes cover image-extraction statuses. Implemented by the downstream
  FTY-376 estimator story.
- **FTY-348 (contract only; no code or migration in this story).** This page is a
  **relocation and de-duplication** of the FTY-324 interpretation/session text that
  previously lived in `parse-candidates.md` (v9), `food-resolution.md` (v16),
  `evidence-retrieval.md` (v6), and `estimator-policy.md` (v3). Those pages now link
  here for the global session/hypothesis semantics and keep their page-local
  responsibilities. No normative clause changes: hypothesis revision,
  deterministic gates, clarification policy, provenance, and privacy/egress are all
  preserved exactly.
- **FTY-324** defined the `InterpretationSession`, the `InterpretationHypothesis`
  fields, the model-consultable decision points, the evidence-tiers-as-tools
  framing, and the sanitized hypothesis-revision trace labels. It added no public
  API, persistence column, provider, prompt, settings, or migration.
- **FTY-325 / FTY-326** implement the interpreter core and the evidence-tier tool
  loop against this target, without adding providers or widening egress.

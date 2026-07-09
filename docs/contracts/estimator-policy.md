# Contract: Estimator Policy

## Purpose

Define the shared estimator policy for natural-language clarification modes,
last-resort clarification, and rough-estimate provenance. This page is the
single contract for the global FTY-298 semantics consumed by the parse,
food-resolution, and evidence-retrieval contracts; those step contracts keep
their schema, routing, source-order, serving-math, evidence-shape, and retention
rules.

This is a contracts/documentation slice only. It changes no endpoint, DTO,
schema, migration, provider, prompt, or estimator behavior.

## Owner

estimator / contracts / backend-core / security-privacy lane:
`backend/app/estimator/clarify_policy.py`, downstream estimator settings, and
the public contracts that consume this policy ([parse-candidates.md](parse-candidates.md),
[food-resolution.md](food-resolution.md), [evidence-retrieval.md](evidence-retrieval.md)).

## Version

1 (FTY-303, contract extraction): relocates the settled FTY-298 clarification
mode and rough-provenance policy from the parse, food-resolution, and
evidence-retrieval contracts into one shared page. Normative behavior is
unchanged from FTY-298.

## Inputs

### Clarify policy config

The natural-language text-log clarify gate is policy-driven. Downstream
implementation stories expose the mode through:

| Variable | Default | Values | Meaning |
| --- | --- | --- | --- |
| `FATTY_ESTIMATOR_CLARIFY_MODE` | `estimate_first` | `estimate_first`, `balanced`, `strict` | Operator-selected abstention posture for natural-language parse/resolution. Unknown values fail closed at config load. |

Optional numeric tunables are contract names for downstream code stories:

| Variable | Default | Bounds | Applies to | Meaning |
| --- | --- | --- | --- | --- |
| `FATTY_ESTIMATOR_PARSE_CLARIFY_THRESHOLD` | unset (`null`) | `0.0`-`1.0` when set | `balanced`, `strict` | Overrides the calibrated parse abstention threshold. It must never make the gate re-ask for a user-stated detail in `balanced`. |
| `FATTY_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR` | `0.6` | `0.0`-`1.0` | rough nutrition facts | Minimum calibrated/cold-pass agreement for accepting a model/default-prior rough nutrition estimate; disagreement leaves a rough/unknown field or asks only for an allowed reason. |
| `FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS` | `2` | `0`-`10` | all modes | Maximum bounded mechanical schema-shape recovery passes before `ParseResult` validation fails closed, such as unwrapping harmless provider wrappers or normalizing enum and numeric field shapes. It does not retry the provider or repair schema-valid active-policy conflicts. |

Invalid enum values, out-of-range floats, and out-of-range attempt counts fail
closed at application config load instead of falling back to an unintended
policy.

## Outputs

### Clarification modes

- **`estimate_first` (default).** Ask only when the estimator cannot identify a
  recognizable food/exercise identity, the input is non-log/gibberish,
  deterministic validators find an impossible or unsafe contradiction, every
  enabled estimator/provider path is unavailable after bounded retries/repair
  attempts, or the relevant estimator path is explicitly disabled. Missing
  quantity alone is not enough to ask: `milk`, `some crackers`, `crackers and
  hummus`, and a bare recognizable exercise identity are accepted as rough
  candidates and resolved downstream with visible rough provenance.
- **`balanced`.** Preserve the calibrated abstention threshold from ADR 0003 /
  FTY-159 for deployments that prefer the measured ask/estimate tradeoff, but
  never re-ask for a detail the user already stated: counts, portions (including
  approximate wording), brands/product identities, explicit nutrition facts,
  exercise durations/distances/steps/games, or standard-serving cues.
- **`strict`.** Maximize precision for deployments that prefer fewer rough
  estimates; older-style amount clarifications for recognizable-but-amountless
  items are allowed. Deterministic plausibility and schema validation still fail
  closed.

### Allowed clarification reasons under `estimate_first`

`needs_clarification` is a rare last resort under the default mode. For a
recognizable item, it is reserved for genuinely indeterminate or unsafe inputs:

- no recognizable identity to estimate, including non-log/gibberish text or a
  component the parser cannot identify as food/exercise after bounded repair;
- deterministic validators find an impossible or unsafe contradiction, including
  implausible quantities or self-contradictory stated nutrition facts;
- every enabled estimator/provider path needed for a rough estimate is
  unavailable, exhausted after retries/repair attempts, or explicitly disabled;
- an operator-selected `balanced`/`strict` mode chooses an amount question for a
  recognizable-but-amountless item.

Across representative everyday logs, the estimator should estimate or resolve
far more often than it asks without encoding a brittle numeric clarification
quota in code.

### Provider-raised clarification

Provider-raised `needs_clarification` output is advisory, not authoritative,
whenever recognized candidates or a recoverable identity can be validated under
the active policy. In `estimate_first`, a provider question that conflicts with
a recognized/recoverable identity is discarded and the candidate is accepted for
rough downstream resolution with content-free assumptions. Only when backend
policy itself allows asking does provider clarification output proceed to the
parse contract's question-quality gate and persistence rules.

### Rough provenance and editability

Rough estimates are valid only when they stay visibly distinguishable from
trusted values and remain user-editable:

- exact source-backed values keep their concrete source (`user_label`,
  `user_text`, `official_source`, `product_database`,
  `trusted_nutrition_database`, or a single `reference_source`) and
  `status = success`;
- comparable aggregates remain rough reference evidence, surfaced by their
  `estimate_basis = comparable_reference` read-model hint and the contributing
  `reference_source:<url>` refs/hashes in `assumptions`;
- pure model-prior or default-serving estimates use `source_type = model_prior`
  (or the concrete source type whose facts were used plus a default-serving
  assumption), a `model_prior`/source `source_ref`, and content-free assumptions
  such as the source miss, serving prior, cold-pass agreement, and active clarify
  mode;
- every rough estimate remains user-editable and visibly distinct from trusted
  database, product, official, label, user-stated, and correction evidence.

Source misses, missing default servings, and unresolvable serving math are
recovery conditions under `estimate_first` when the item identity is
recognizable. Resolution falls forward through applicable evidence tiers and
rough default/model-prior estimation before asking. The rough path still fails
closed for unsafe contradictions, implausible facts, schema-invalid provider
output, missing recognizable identity, disabled/unavailable estimator paths
after bounded retries, or an operator-selected stricter mode.

## Validation

The active policy never bypasses schema validation, deterministic plausibility
checks, or source/fact validation owned by the step contracts. It changes only
whether a validated recognizable item falls forward to rough estimation or asks
for more detail.

## Authorization

This policy defines routing and provenance semantics only. User-owned rows,
object ownership, and `ON DELETE` behavior remain owned by the parse,
food-resolution, evidence, and log-event contracts that persist data.

## Privacy and Retention

Rough/default/model-prior diagnostics and provenance are content-free. Traces,
source refs, assumptions, diagnostics, logs, calibration artifacts, and contract
examples must never store or echo raw diary text, raw provider output, raw
prompts, raw fetched/source payloads, provider error bodies, request/response
bodies, URLs with secrets, tokens, keys, or other credentials outside explicit
user-owned fields whose contract permits that content.

Untrusted natural-language input, provider output, fetched pages, OCR text, and
tool output stay untrusted until trusted backend code schema-validates and
bounds them. Privacy and retention rules for concrete persisted objects remain
owned by [parse-candidates.md](parse-candidates.md), [food-resolution.md](food-resolution.md),
[evidence-retrieval.md](evidence-retrieval.md), and [docs/security/data-retention.md](../security/data-retention.md).

## Errors

Invalid policy configuration fails closed at application config load. At runtime,
the step contracts own concrete failure labels and transitions; this policy only
defines when clarification is allowed under the active mode.

## Examples

```
event.raw_text = "crackers and peanut butter"
  -> provider asks "How much?" or samples disagree
  -> estimate_first sees recognizable identities and no unsafe contradiction
  -> provider question is advisory; candidates continue to rough resolution
  -> downstream evidence records default/reference/model-prior provenance
  -> no clarification is asked solely because quantity is missing
```

```
event.raw_text = "stuff"
  -> no recognizable food or exercise identity survives validation/repair
  -> estimate_first has no safe object to estimate
  -> the parse step asks a targeted question when one can help, otherwise fails closed
```

## Migration / Compatibility

FTY-303 is documentation-only extraction. It introduces no migration,
compatibility shim, endpoint change, DTO change, schema change, provider change,
prompt change, or estimator behavior change.

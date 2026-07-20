# Contract: Estimate-First Routing & User-Stated Nutrition

## Purpose

Define the parse step's **estimate-first routing override** and its
**user-stated-nutrition extraction** rules: how a recognizable-but-underspecified
entry is estimated rather than re-asked, how the deterministic **detail signal**
strengthens that decision, how the deterministic **amount fills** (range midpoint
/ stranded count) recover a missing count before the plausibility gate, and how
an explicit nutrition fact the user wrote is extracted as untrusted evidence.

This is the settled routing/detail-signal slice of the parse step
([parse-candidates.md](parse-candidates.md)), relocated here (FTY-364) so the
parse contract stays focused on the `ParsedCandidate` shape, validation, and
persistence. It carries **no normative change**: the FTY-167 / FTY-275 / FTY-279 /
FTY-298 / FTY-362 rules are moved verbatim in meaning. It interprets the shared
mode semantics owned by [estimator-policy.md](estimator-policy.md) and feeds the
resolution boundaries owned by [food-resolution.md](food-resolution.md)
(**User-Stated Resolution**) and
[food-resolution-official-source.md](food-resolution-official-source.md)
(**Official-Source Resolution**).

## Owner

estimator / contracts / backend-core lane:
`backend/app/estimator/detail_signals.py`, `backend/app/estimator/parse.py`,
`backend/app/estimator/clarify_policy.py`, `backend/app/estimator/plausibility.py`,
`backend/app/schemas/parse.py` (the `stated_*` fields).

## Version

1 (FTY-364, contract only): extracts the `### Estimate-first routing override`
and `### User-stated nutrition facts` sections from
[parse-candidates.md](parse-candidates.md) (which carried them through FTY-362,
v-note only) into this dedicated page with no normative change. The
FTY-167/FTY-275/FTY-279/FTY-298/FTY-362 routing, detail-signal, amount-fill, and
user-stated-nutrition rules stay semantically unchanged; the parse page now links
here for them.

## Estimate-first routing override (FTY-167, FTY-298)

A casual entry is often returned by the model with a conservative confidence (or even a
`needs_clarification` disposition) even though it already carries enough real-world
structure to estimate — "a handful (5-10) of onion rings", "3 cracker sandwiches", "ran 5
km", "played 3 games of badminton". Before routing such a reply to clarification, the step
checks each extracted item against the active shared clarification policy
([estimator-policy.md](estimator-policy.md)). The older **deterministic detail signal**
(`app/estimator/detail_signals.py`) remains a strengthening signal:

- **food** — a positive structured `amount` (a count or a measured quantity), a
  numeric **range** in `quantity_text` (`5-10`), a **stranded bare count** (FTY-362; a
  delimited whole number left in `quantity_text` — see **Deterministic amount fills**
  below), a **stated worded portion** (FTY-275): a household / cooking measure (`cup`, `tsp`, `tbsp`,
  `fl oz`, `pint`, `quart`, `gallon` and their spellings), a colloquial / approximate
  measure word (`splash`, `drizzle`, `dash`, `pinch`, `handful`, `glug`), an
  indefinite-article measure (`a`/`an` = one), **a stated serving/count unit**
  (FTY-382 — `1 serving`, `a serving`, `2 servings`, `1 bar`, and the plain
  count/portion vocabulary the FTY-156 plausibility validator recognizes in
  `plausibility._COUNT_UNITS`, recognised from the structured `unit` or a bare
  serving/count word left in `quantity_text`, excluding the empty no-unit sentinel);
  **or a stated nutrition fact**
  (FTY-279 — a `stated_calories` total or a `stated_*` macro the user wrote). Each
  means the user *stated* a usable detail, so a generic source-miss defers to estimation
  (or, for a stated nutrition fact, resolves directly from that `user_text` evidence)
  rather than re-asking — see `food-resolution.md` (**User-Stated Resolution (FTY-279)**
  no-second-follow-up rule) and `food-resolution-official-source.md`
  (**Official-Source Resolution**, v8). Under the default
  `estimate_first` policy a bare recognizable identity with **no** stated portion and no
  stated nutrition fact (`milk`, `some crackers`) still attempts a rough estimate; under
  `balanced`/`strict` it may lack the stronger detail signal used by the abstention path;
- **exercise** — an explicit duration, a **distance**, a **step count**, or a **game count**.

When the sample set would otherwise clarify (a hybrid score below the calibrated
operating point or a provider `needs_clarification` disposition), the parse step applies
the shared mode semantics and allowed clarification reasons from
[estimator-policy.md](estimator-policy.md). Bounded schema-shape repair is not an
independent clarification branch: a repaired trusted `ParseResult` routes through the same
disposition, confidence/agreement, recognizable-identity, plausibility, stated-nutrition
safety, and active-policy gates as any other sample. Under the default policy missing
amounts become downstream rough assumptions, not parse questions; a calibrated-confident
sample set never enters the clarify branch, and the plausibility gate (FTY-156,
[parse-candidates.md](parse-candidates.md)) still runs on accepted items.

**Deterministic amount fills (range midpoint / stranded count).** When a food item has
no structured `amount` the step recovers one from `quantity_text`: a numeric **range**
fills its **midpoint** (`5-10 → 7.5`, assumption `range_midpoint`; FTY-167), and a
stranded stated **count** the model left in the phrase (`(i had 4)`, `2 large`,
`4 toppables brand crackers`) is lifted as the count (assumption `stated_count`; FTY-362)
so it reaches the count / common-portion / model-prior scaling instead of being dropped
and re-asked. Only a **count** is recovered, never a *detail* numeral: a measured
mass/volume (owned by the serving math) and a range are excluded first — measured
exclusion covers a multi-word unit (`1 fl oz`, `1 fluid ounce`), not just single-token
`100 g` / `1 tbsp` — and the count recognizer matches only a delimited whole number, so a
percentage (`2% milk`), a fraction (`1/3 cup`), a decimal (`1.5`), and a product-number
hint glued to letters (`7up`, `v8`, `12ct`) are left in place. Both fills happen **before**
the FTY-156 plausibility gate, bounded by the same count caps (`500-1000 → 750` and a
40-count clarify rather than bypassing it); the assumption is recorded only on acceptance.

## User-stated nutrition facts (FTY-279)

When the user writes an explicit nutrition fact — a calorie total (`580 cals`,
`580 calories`, e.g. "Sobeys buffalo chicken lime wrap (580 cals idk the
breakdown)"), a macro (`30g protein`), or both — the parser extracts it into the
`stated_*` fields on that item's candidate rather than dropping it. Common calorie
and macro phrasings (`cal`/`cals`/`calories`/`kcal`; `30g protein`, `30 g protein`)
all resolve to the same `stated_*` field. The rule refines "No energy": the parser still **invents no
number**, but it is allowed to **read what the user stated** and carry it as
untrusted evidence.

- **Extract, don't invent.** A `stated_*` field is filled **only** from a value the
  user actually wrote for that item; an unstated field is `null`. The model must not
  synthesize a calorie/macro number the user did not give (that is the resolution
  layers' job, with their own provenance), and it never copies a value from one item
  onto another.
- **As-logged.** `stated_*` values are the totals for the exact item as logged, not
  per-100g/per-serving. The honest basis and per-field provenance are fixed in
  `evidence-retrieval.md` (`as_logged`, `field_provenance`); the parser only carries
  the raw stated numbers.
- **Bounded & untrusted.** Each field is finite, `≥ 0`, and schema-capped; an
  out-of-range/negative/non-finite value makes the reply schema-invalid and fails
  closed. Extracted facts back a persisted number only after the food step's
  plausibility validation (as-logged abuse cap + Atwater internal-consistency);
  a self-contradictory claim clarifies rather than committing (`food-resolution.md`).
- **Prompt-injection safe.** The stated numbers are stored as data through
  parameterized inserts and never interpreted; an instruction embedded in the entry
  text is never executed (as for every `ParsedCandidate` field).

A stated nutrition fact is a **detail signal** (above): a recognizable item that
carries one is estimated/resolved, **not** re-asked for an amount — see the
no-second-follow-up rule in `food-resolution.md`.

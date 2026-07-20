# Contract: Clarify-Decision Gates

## Purpose

Define the parse step's **estimate-vs-ask gate machinery**: the calibrated
clarify decision (ADR 0003 Layer C), the model-free deterministic plausibility
gate, and the trailing gate-outcome rules that govern what a gate-raised
clarification must look like and how candidates + questions are committed.

This is the settled gate slice of the parse step
([parse-candidates.md](parse-candidates.md)), relocated here (FTY-385) so the
parse contract stays focused on the `ParsedCandidate` / `ParseResult` shape,
provider-output repair, persistence, validation, authorization, privacy, errors,
and examples. It carries **no normative change**: the FTY-156 / FTY-159 /
FTY-278 / FTY-298 rules are moved verbatim in meaning. It interprets the shared
mode semantics owned by [estimator-policy.md](estimator-policy.md), runs after
the estimate-first routing override ([estimate-first-routing.md](estimate-first-routing.md)),
and feeds the clarify-loop read/answer flow owned by
[clarification.md](clarification.md).

## Owner

estimator / contracts / backend-core lane:
`backend/app/estimator/clarify_policy.py`,
`backend/app/estimator/plausibility.py`,
`backend/app/estimator/self_consistency.py`,
`backend/tests/test_clarify_calibration.py`,
`backend/tests/fixtures/parse_calibration/calibration_summary.json`.

## Version

1 (FTY-385, contract only): extracts the `### Calibrated clarify decision` and
`### Deterministic plausibility gate` sections — with their trailing
gate-outcome, question-quality, atomicity, and item-scoped partial clarification
(FTY-278) rules — from [parse-candidates.md](parse-candidates.md) into this
dedicated page with no normative change. The FTY-156/FTY-159/FTY-278/FTY-298 gate
rules stay semantically unchanged; the parse page now links here for them.

## Calibrated clarify decision (FTY-159, ADR 0003 Layer C)

The estimate-vs-ask decision is a **measured operating point over a measured
signal**, not a hand-picked constant (the retired
`PARSE_CONFIDENCE_CLARIFY_THRESHOLD = 0.45` was an unprincipled guess; a fixed
uncalibrated threshold is fragile under distribution shift — Kamath, Jia &
Liang, ACL 2020, via `docs/adr/0003-estimator-confidence-clarification.md`,
which owns the architecture decision this implements):

- **Signal — the bake-off winner.** Over the labeled calibration sets (the
  FTY-157 synthetic band + the FTY-169 naturalistic band, scored `combined` by
  the FTY-157 harness), three signals were compared on risk-coverage curves:
  the verbalized confidence, the FTY-158 sampling-agreement score, and their
  hybrid (`0.6 × agreement + 0.4 × verbalized`). The **hybrid won** and is what
  the gate consumes: at the target precision the verbalized baseline reaches
  only 40% coverage and agreement-only never reaches it at all. A sample set
  with **no `parsed` sample** has no hybrid score to trust (its agreement can be
  a perfect 1.0 *about asking*), so the active FTY-298 policy owns routing:
  under `estimate_first`, clarification-only samples with a recognizable
  schema-validated identity are advisory and may be accepted as rough candidates;
  under `balanced`/`strict`, or when `estimate_first` has no recognizable
  identity or another allowed clarification reason applies, the set routes to
  clarification or failure.
- **Operating point — derived, with a margin.** The threshold is chosen on the
  winning signal's risk-coverage curve for a **target answered precision of
  0.99** (of the events the gate estimates, ≥ 99% must be gold-estimate —
  under-asking silently corrupts an honest count, so precision is the
  calibration target; maximizing coverage under it then minimizes over-asking),
  and committed as the midpoint of the empirical margin band around the
  selected point. Measured on the combined set: over-ask 12.4% → 6.5%,
  under-ask 19.4% → 1.9%, correct decisions 85.2% → 95.1% versus the retired
  gate. **Provenance caveat:** both calibration bands are author-constructed
  stand-ins, not recorded user traffic — the synthetic band is synthetic by
  construction, and the naturalistic band's "recorded" samples were authored
  alongside this calibration (`generate_naturalistic_seed.py`, provenance
  declared per record via `source_kind`; see the fixture README) — so the
  operating point and the improvement rates above quantify an authored
  simulation until a live-recorded band replaces the stand-ins. The constant
  lives in `app/estimator/clarify_policy.py`
  (`NL_PARSE_CLARIFY_POLICY`); the committed derivation is
  `backend/tests/fixtures/parse_calibration/calibration_summary.json`.
- **Regression gate.** `backend/tests/test_clarify_calibration.py` re-derives
  the bake-off on every verification run **from the committed static fixtures —
  no provider is invoked**: the production constant must equal the derived
  point, the committed artifact must match a fresh derivation, the calibrated
  decision must keep beating the verbalized-vs-0.45 baseline, and absolute
  floors (correct-decision rate, precision, over-/under-ask, coverage) must
  hold. The gate therefore catches fixture, signal-code, or selection-rule
  changes only; a prompt or model change leaves every fixture-derived number
  identical and CI green. Recalibrating after a prompt or model change is a
  **manual step**: re-run the harness bake-off over re-recorded or live
  provider outputs and recommit the derivation.
- **The label path shares the mechanism.** The nutrition-label gate
  (`label-extraction.md`) routes through the same `ClarifyPolicy` type
  (`LABEL_CLARIFY_POLICY`). Its operating point is a **documented tunable**
  (the conservative pre-FTY-159 value, 0.5, over the panel's verbalized
  confidence): the calibration sets are NL descriptions, not label-image scans,
  so a data-derived label point would be fabricated — a dedicated label-image
  eval slice is the recorded follow-up that earns one.
- **Cost.** Sampling costs ~N× the tokens of a single parse call; latency stays
  near-flat (parallel samples), and the early stop keeps stable inputs at 2
  calls (ADR 0003, Consequences).

## Deterministic plausibility gate (FTY-156)

After confidence/disposition routing, a model-free gate
(`app/estimator/plausibility.py`, `check_candidate`) checks each **food**
candidate's quantity against coarse physical/serving sanity ranges before the
parse is trusted. A single implausible food candidate makes the event's total
untrustworthy, so the step routes the whole event to `needs_clarification`
(`implausible_candidate`) with one targeted question naming the offending item,
and persists no candidates.

- **Bounds** (generous, documented tunables in `plausibility.py`): a generic
  discrete count above `MAX_PLAUSIBLE_COUNT` (`250`) fails, while clearly large
  counted foods use `MAX_PLAUSIBLE_LARGE_ITEM_COUNT` (`36`) so examples such as
  `50 eggs` still route to clarification without rejecting realistic small-food
  logs such as `50 blueberries` or food-specific units like `50 crackers`. A mass
  above `MAX_PLAUSIBLE_GRAMS` (`2000 g`) or a volume above `MAX_PLAUSIBLE_ML`
  (`2000 ml`) fails. A numeric amount on an unrecognised unit fails above
  `MAX_PLAUSIBLE_UNKNOWN_UNIT_AMOUNT` (`36`) unless the unit appears to be a
  food-specific count unit matching the candidate name, in which case the count
  cap applies. Every explicit `<number> <mass|volume unit>` measure in
  `quantity_text` is checked against the same mass/volume bounds even when
  structured fields are absent or describe a count/portion such as `1 serving`.
  A candidate with no structured `amount` and no explicit measured quantity in
  `quantity_text` passes (inference gaps are the confidence check's concern).
  Bounds are set just above any realistic single-entry portion so a false reject
  of a large-but-real meal is effectively impossible; the fail-safe is loose (an
  over-generous bound lets one absurd parse through rather than falsely asking).
- **Exercise candidates are excluded.** Their quantities are durations
  (minutes/hours), not mass/volume/count, so the food-portion bounds and unit
  vocabulary do not apply — exercise plausibility/duration parsing belongs to
  FTY-043 (`exercise-burn.md`). Running an exercise duration through this gate
  would falsely reject ordinary workouts (e.g. `walking, 60 minutes`).

Provider `needs_clarification` output is first checked against the shared advisory
provider rule ([estimator-policy.md](estimator-policy.md)). Only when backend policy
itself allows asking does provider clarification output have to be persisted; at that
point a missing specific question, a generic fallback question, or fewer than two
quick-pick options fails closed (`StepFailed("clarification_quality_failed")`) and
persists nothing. A
`needs_clarification` event therefore never reaches the answer flow with a
model-raised generic placeholder. If the active policy routes a low-confidence `parsed`
sample to clarification and no provider question was supplied, the parse step
synthesizes one targeted backend question naming the first item that still satisfies an
allowed clarification reason and persists 2–5 bounded quick-pick options.
Deterministic backend gates that synthesize their own targeted question without
meaningful quick-picks persist that question with `options: []`.
Candidates and questions are committed in the **same transaction** as the
terminal status, so a completed/clarification outcome and its rows are atomic.
When a **re-estimate** of an answered event (`clarification.md`, Clarification
answer) lands on `needs_clarification` again, the fresh round's questions
**replace** the event's unanswered question rows in that same transaction —
answered questions and their `clarification_answers` are preserved, since they
carry the accumulated details the re-estimate consumes — so the clarification
read (status-gated to `needs_clarification`; `clarification.md`) serves exactly
the fresh round's open questions.

**Item-scoped partial clarification (FTY-278, contract only).** Under the
item-scoped contract, a mixed entry is not all-or-nothing: the step commits the
entry's **costable** components as `resolved` items (via the downstream food
step, `food-resolution.md`) and raises a clarification only for the component(s)
that still have an allowed clarification reason after the active FTY-298 policy has
tried rough estimation, each question carrying its
`derived_food_item_id`. Such a `partially_resolved` event (`log-events-history.md` v6)
therefore carries committed `resolved` siblings alongside its open item-scoped
questions — the
event's derived-item set (resolved siblings + the `unresolved` component)
and its question rows are committed atomically in the terminal transaction. A
re-estimate re-costs **only the open component** and leaves the already-`resolved`
siblings untouched, so a resolved sibling is represented exactly once
and never duplicated or double-counted, and the fresh round's questions replace
only the **unanswered** ones (`estimation-jobs.md` v3, `daily-summary.md`). This
paragraph is the target contract; the estimator work to persist siblings and
populate `derived_food_item_id` is the FTY-278 implementation follow-up. The
historical **FTY-275 baseline** was whole-event, event-level clarification with
nothing committed; FTY-298 now makes recognizable amountless components rough
estimate first, and any remaining question stays item-scoped under this target.

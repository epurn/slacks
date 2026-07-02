# Parse calibration fixture

This directory contains the FTY-157 offline calibration/evaluation set for the
natural-language parse step's estimate-vs-ask decision.

## Schema

Each line in `examples.jsonl` is one JSON object:

- `id`: stable lowercase fixture identifier.
- `difficulty`: one of `unambiguous`, `inferable`, or `indeterminate`.
- `source_kind`: always `synthetic_by_construction` for committed examples.
- `source_template`: the synthetic generator template that created the example.
- `input`: the natural-language log text.
- `gold_decision`: `estimate` when the parser should proceed with candidates, or
  `needs_clarification` when it should ask before estimating.
- `gold_parse`: the expected parsed candidates. Each candidate mirrors
  `ParsedCandidate`: `type`, `name`, `quantity_text`, optional `unit`, optional
  `amount`, optional `brand`, and optional `barcode`. No calories or macros live
  in this fixture.
- `baseline`: the recorded offline stand-in for the current
  verbalized-confidence-vs-`0.45` parse gate. The default harness uses this field
  so verification never calls a live model.
- `samples` (FTY-158): three recorded parse samples standing in for
  temperature>0 sampling of the live model. Each validates as a full
  `ParseResult` (`disposition`, `confidence`, `items`, optional
  `clarification_questions`), so the production self-consistency metric
  (`app/estimator/self_consistency.py`) consumes them unchanged. Like the
  `baseline` field, they keep the consistency signals fully offline and
  deterministic.

The fixture schema is enforced by `tests.parse_calibration.harness` and
`tests/test_parse_calibration_harness.py`.

## How the recorded samples are constructed

Samples are synthetic by construction, per difficulty band (see
`generate_fixture.py` for the exact deterministic schedules):

- `unambiguous`: all three samples are the identical gold parse — an easy input
  parses stably, so the production early-stop rule (unanimous first window)
  always fires.
- `inferable`: mostly unanimous, plus a deterministic minority with a mild
  amount jitter on one sample (agreement stays high) and another minority with
  a disposition flip (agreement drops to 1/3 and the input pays the full N).
- `indeterminate`: samples diverge — guessed portions a factor of two apart
  plus a disposition flip — except two honest failure classes: a unanimous-ask
  class (all samples clarify → the direct fail-closed decision) and a
  consistent-but-wrong class (the same invented portion every sample —
  self-consistency's documented blind spot, kept so the measured improvement
  is not fake-perfect).

Divergence always appears inside the first sampling window (sample 2), because
the production early-stop rule never draws later samples when the first window
is unanimous — late-only divergence would, correctly, be invisible.

`baseline_summary.json` is the committed baseline metrics
(`--write-baseline`); `self_consistency_summary.json` is the committed hybrid
consistency+verbalized metrics (`--signal hybrid --write-summary`). Both are
regression-pinned by `tests/test_parse_calibration_harness.py`, which also
asserts the improvement bar: hybrid and agreement-only must measurably beat
the recorded verbalized baseline at the 0.45 operating point.

## How examples are made

Committed examples are synthetic by construction. The generator starts from a
known parse and a known `gold_decision`, then renders the input string from that
record. Gold labels are therefore not inferred from private logs or guessed by a
model.

The difficulty bands mean:

- `unambiguous`: explicit quantities or durations, e.g. `2 eggs and 30 min run`.
- `inferable`: an estimate-first case with enough structure to infer a typical
  portion, e.g. `a bowl of oatmeal`.
- `indeterminate`: a food or exercise is named, but the amount/duration is not
  recoverable from the text, e.g. `crackers and peanut butter`.

Run `cd backend && python -m tests.parse_calibration.harness` to print the
human-readable table, or pass `--json` for machine-readable metrics. Pass
`--signal {baseline,agreement,hybrid}` to pick the recorded signal to evaluate
(default `baseline`), and `--write-summary PATH` to write the selected
signal's summary JSON. Live (token-spending) evaluation of the
self-consistency signal against a real provider is opt-in via
`tests.parse_calibration.harness.live_self_consistency_signal` — it is never
run by default verification.

## Adding examples

Prefer extending `generate_fixture.py` so the fixture stays reproducible. If a
manual synthetic case is needed, add it as one JSONL record and keep the same
schema. The integrity test will reject duplicate ids, invalid candidate shapes,
and records that are not marked `synthetic_by_construction`.

Do not commit real dogfooding logs, user entries, private nutrition history,
emails, names, phone numbers, addresses, screenshots, OCR text, provider output,
or any other personal data. If the user wants to compare against real local
entries, keep that file outside the repository and pass it to a local wrapper;
the public fixture must remain synthetic-only.

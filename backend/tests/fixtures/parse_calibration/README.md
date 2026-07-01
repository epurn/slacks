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

The fixture schema is enforced by `tests.parse_calibration.harness` and
`tests/test_parse_calibration_harness.py`.

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
human-readable table, or pass `--json` for machine-readable metrics.

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

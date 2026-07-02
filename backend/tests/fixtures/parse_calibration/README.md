# Parse calibration fixture

This directory contains the FTY-157 offline calibration/evaluation set for the
natural-language parse step's estimate-vs-ask decision, plus the FTY-169
**naturalistic band** (`naturalistic_examples.jsonl`) and its cross-provider
judge protocol.

## Bands

- **Synthetic** (`examples.jsonl`, FTY-157) — clean, correct-by-construction NL
  inputs. Gold labels fall out of the generator (`generate_fixture.py`).
- **Naturalistic** (`naturalistic_examples.jsonl`, FTY-169) — messy,
  real-world-*style* NL inputs (casual phrasing, ranges like `5-10 onion rings`,
  brand shorthand like `kraft PB`, multi-item entries, hedges, minor typos)
  across the same three difficulty strata. These are **not**
  correct-by-construction; the labeling path that *earns* their gold labels is
  the cross-provider judge protocol below. The committed seed's labels are
  author-constructed stand-ins (`source_kind` records this honestly — see the
  schema) pending the maintainer's live dual-judge pass. Every input is
  **authored** — realistic in style, never scraped from a real user.

Both bands share the labeled-example schema and are scored by the same harness.
A run reports a single band or the `combined` union (`--band`). FTY-159
calibrates the operating point over `combined`.

## Schema

Each line in `examples.jsonl` / `naturalistic_examples.jsonl` is one JSON object:

- `id`: stable lowercase fixture identifier.
- `difficulty`: one of `unambiguous`, `inferable`, or `indeterminate`.
- `band` (FTY-169): `synthetic` (default; omitted in the FTY-157 fixture) or
  `naturalistic`.
- `source_kind`: how the gold label was produced —
  `synthetic_by_construction` (FTY-157), or, for the naturalistic band,
  `authored_naturalistic` (an author-constructed unambiguous case,
  agreement-trivial by construction) or `recorded_stand_in` (an
  author-constructed label whose recorded stand-in judge outputs exist to pin
  the router offline; no live judge produced it). `cross_provider_judge` is
  **reserved** for labels the live independent Claude + GPT-5.5 protocol below
  actually produced — no committed example carries it until the maintainer's
  live pass lands.
- `source_template`: the generator template / naturalistic style that created
  the example.
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
- `samples` (FTY-158, extended to the naturalistic band by FTY-159): three
  recorded parse samples standing in for temperature>0 sampling of the live
  model. Each validates as a full `ParseResult` (`disposition`, `confidence`,
  `items`, optional `clarification_questions` objects with `text` and `options`),
  so the production self-consistency metric (`app/estimator/self_consistency.py`)
  consumes them unchanged. Like the `baseline` field, they keep the consistency signals fully
  offline and deterministic. Both bands carry them (the naturalistic band's are
  author-constructed stand-ins declared per case in
  `generate_naturalistic_seed.py`, mirroring the synthetic schedules below), so
  the FTY-159 bake-off can score every signal over the `combined` set.

The fixture schema is enforced by `tests.parse_calibration.harness`,
`tests/test_parse_calibration_harness.py`, and (naturalistic band)
`tests/test_naturalistic_calibration.py`.

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

## FTY-159 bake-off and the calibrated operating point

`calibration_summary.json` is the committed FTY-159 signal bake-off over the
**combined** band (`python -m tests.parse_calibration.harness --bake-off
--write-summary …`): every recorded signal gets an operating point derived at
the target answered precision (0.99 — see `TARGET_ANSWERED_PRECISION` in the
harness for why precision, not raw correct rate, is the target), and the winner
(the **hybrid**) supplies the production clarify threshold
(`app/estimator/clarify_policy.py`, `NL_PARSE_CLARIFY_POLICY`). The committed
threshold is the midpoint of the empirical margin band around the selected
operating point, so it never sits exactly on an observed score.
`tests/test_clarify_calibration.py` is the regression gate: it re-derives the
bake-off, pins the artifact, asserts the production constant equals the derived
point, and enforces the improvement-over-baseline bar plus absolute floors.

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

Pass `--band {synthetic,naturalistic,combined}` to score a whole band instead of
`--fixture` (e.g. `python -m tests.parse_calibration.harness --band naturalistic`);
every recorded signal scores every band. Pass `--bake-off` to run the FTY-159
signal bake-off and operating-point derivation instead of a single-signal run.

## Cross-provider judge protocol (FTY-169)

The naturalistic band's gold labels are **not** correct-by-construction, so they
are produced by an independent two-provider judge — grading a model's parse with
the *same* model is circular (it inherits that model's calibration blind spots,
per the estimator research), whereas two independent providers agreeing is a
materially stronger label and their *disagreement* is exactly the signal that an
example is genuinely contestable and deserves a human.

The tooling lives in `tests/parse_calibration/judge.py`. It is **offline
maintainer tooling, never on the default `./verify.sh` path.**

- **Two independent judges.** Each input is labeled independently by **Claude**
  (the first-party `claude_code` subscription path — plan-covered login, no API
  key) and **GPT-5.5** (the `codex` CLI subscription login, headless). Each
  returns a `JudgeLabel` (the gold ask-vs-estimate decision + the gold parse,
  mirroring `ParsedCandidate`) — never a self-reported confidence.
- **Agreement → accept; disagreement → adjudicate.** The router (`adjudicate`)
  accepts when the two labels agree (same decision, and — for `estimate` — the
  same items by kind+normalized name with amounts within a 20% tolerance) and
  commits the agreed label to `naturalistic_examples.jsonl`. A disagreement is
  written to `naturalistic_adjudication_queue.jsonl` with **both** judges'
  outputs; the maintainer resolves it, and only then does an adjudicated label
  enter the committed set. The queue is small by design — concentrated on the
  genuinely indeterminate cases.
- **No paid API key, ever (FTY-086).** The GPT-5.5 judge rides the `codex` login
  session only: `CodexCliProvider` forwards a strict env allowlist that
  **excludes `OPENAI_API_KEY`** (and every other provider key) to the
  subprocess, and never reads one. Without a login (or the binary) the judge
  raises a configuration error and `run_protocol` **fails the batch closed** with
  a clear message — it never fabricates a label. The tooling is inert without the
  maintainer's local logins.
- **No credential is ever committed** — not in the seed, the judge run, the
  queue, or these docs.

### Running the live dual-judge pass (maintainer opt-in)

With local `claude` and `codex` logins present:

```
cd backend && python -m tests.parse_calibration.judge \
  --inputs path/to/inputs.txt \
  --accepted-out /tmp/accepted.jsonl \
  --queue-out /tmp/queue.jsonl
```

`inputs.txt` is one authored diary entry per line, kept **outside** the repo if
it is derived from real local entries (see the no-PII rule below). The command
prints the observed agreement rate and fails closed (exit 2) if a login is
absent. Fold accepted labels into the seed (adding `band`/`source_kind`/
`baseline`) and adjudicate the queue before committing.

### Recorded stand-in judge run and its reproduction rate

`naturalistic_judge_run.json` is an **author-constructed stand-in** for both
judges' outputs over the seed's judged inputs — a deterministic offline
router-regression fixture (mirroring FTY-158's recorded samples), **not** real
user data and **not** the output of any live judge run. The matching seed rows
carry `source_kind: recorded_stand_in`, never `cross_provider_judge`.
`test_cross_provider_judge.py` re-runs the router over it and asserts it
reproduces the committed seed and queue exactly, so the accept/adjudicate flow
is proven offline with no live model.

**Recorded stand-in reproduction rate: 12/14 ≈ 85.7%** of the stand-in judged
inputs agree and are accepted into the seed; the remaining 2 are in the
adjudication queue. This is a designed property of the fixture — it pins the
accept-most/queue-few shape the router must reproduce — **not an observed
inter-judge agreement rate**; no live cross-provider judgment has happened yet.
(The author-constructed `authored_naturalistic` cases are agreement-trivial by
construction and are not part of this rate.) The maintainer's live dual-judge
pass records the first real observed agreement rate and replaces this fixture.

## Adding examples

**Synthetic band:** prefer extending `generate_fixture.py` so the fixture stays
reproducible. If a manual synthetic case is needed, add it as one JSONL record
and keep the same schema. The integrity test rejects duplicate ids, invalid
candidate shapes, and records not marked `synthetic_by_construction`.

**Naturalistic band:** add authored inputs to `generate_naturalistic_seed.py`
and regenerate (`python -m tests.fixtures.parse_calibration.generate_naturalistic_seed`),
which rewrites the seed, the judge run, and the queue consistently. Each
committed case declares its recorded-sample `sampling` schedule (`unanimous`,
`jitter`, `flip`, `divergent`, `unanimous_ask`, `consistent_wrong` — see the
generator docstring); after regenerating, re-run the bake-off write
(`--bake-off --write-summary`) so `calibration_summary.json` stays consistent. A judged case
(`recorded_stand_in`) must carry agreeing stand-in judge outputs; a `contested`
case goes to the queue and is excluded from the seed; an `authored_naturalistic`
case is an author-constructed unambiguous label. The generator never emits
`cross_provider_judge`: only a real run of the judge CLI above earns that kind —
fold in only the agreed/adjudicated labels it produces, tagged
`cross_provider_judge`, replacing the stand-in labels for those inputs.

Do not commit real dogfooding logs, user entries, private nutrition history,
emails, names, phone numbers, addresses, screenshots, OCR text, provider output,
or any other personal data. Both bands are **synthetic/authored only**. If the
user wants to compare against real local entries, keep that file outside the
repository and pass it to the local judge/harness wrapper; the public fixtures
must remain synthetic-only.

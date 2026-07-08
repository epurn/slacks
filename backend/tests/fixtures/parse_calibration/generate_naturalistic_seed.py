"""Generate the FTY-169 naturalistic calibration seed and its judge artifacts.

The naturalistic band is messy, real-world-*style* diary text — casual phrasing,
ranges ("5-10 onion rings"), brand shorthand ("kraft PB"), multi-item entries,
hedges, minor typos — across the three FTY-157 difficulty strata. Unlike the
synthetic band it is **not** correct-by-construction. The intended labeling path
is the cross-provider judge protocol (``tests/parse_calibration/judge``,
documented in ``README.md``): Claude and GPT-5.5 label each input independently,
agreement is accepted, disagreement is queued for a human. **This seed has not
been through that live protocol yet** — every label below is author-constructed,
and the "judge outputs" are deterministic stand-ins that exist to pin the router
offline, exactly like FTY-158's recorded samples.

Every input here is **authored** — realistic in *style*, never scraped from a
real user. The `fatty` repo is public and real diary entries are PII
(``docs/security/data-retention.md``); no real user data is ever committed.

This generator holds the authored cases and their *recorded* judge outputs
(deterministic offline stand-ins, mirroring FTY-158's recorded samples) and
writes three consistent artifacts so the committed set, the judge run, and the
queue can never drift:

- ``naturalistic_examples.jsonl`` — the committed seed (stand-in-judged cases +
  author-constructed unambiguous cases), each a full ``LabeledParseExample``
  tagged ``band: naturalistic``.
- ``naturalistic_judge_run.json`` — the recorded stand-in two-judge outputs for
  the judged/contested inputs, from which ``run_protocol`` reproduces the seed
  and the queue offline (see ``test_cross_provider_judge.py``).
- ``naturalistic_adjudication_queue.jsonl`` — the contested inputs (both judges'
  outputs) awaiting maintainer adjudication; they are **not** in the seed.

Provenance per case:

- ``authored`` — an author-constructed unambiguous case (agreement-trivial by
  construction); committed with ``source_kind: authored_naturalistic``; not in
  the judge run.
- ``judged`` — the stand-in judges agree; committed with ``source_kind:
  recorded_stand_in``; in the judge run with agreeing labels.
- ``contested`` — the stand-in judges disagree; **not** committed to the seed;
  in the judge run and the queue.

FTY-159: each committed case also carries ``samples`` — N=3 recorded parse
samples standing in for temperature>0 sampling of the live model, exactly like
the synthetic band's (``generate_fixture.py``), so the FTY-159 signal bake-off
(verbalized vs self-consistency vs hybrid) can be scored over the **combined**
labeled set, not just the synthetic band. Each case names its deterministic
``sampling`` schedule:

- ``unanimous`` — three identical parses of the gold label (a stable input).
- ``jitter`` — sample 2 carries a mild amount jitter on the first item
  (agreement stays high; the contested window pays the full N).
- ``flip`` — one sample flips to ``needs_clarification`` (agreement 1/3): an
  honest over-ask case for the consistency signals on an estimable input.
- ``divergent`` — guessed portions a factor of two apart plus a disposition
  flip: the indeterminate shape self-consistency is built to catch.
- ``unanimous_ask`` — every sample asks: the direct fail-closed decision.
- ``consistent_wrong`` — the same invented portion every sample:
  self-consistency's documented blind spot, kept so the measured improvement
  over the messy band is not fake-perfect.

Like everything else in this seed the samples are author-constructed stand-ins,
never live model output; divergence always appears inside the first sampling
window (sample 2) because the production early-stop rule never draws later
samples when the first window is unanimous.

``source_kind: cross_provider_judge`` is **reserved** for labels the live
protocol actually produced. This generator never emits it: when the maintainer's
live dual-judge pass lands, its agreed/adjudicated labels replace the stand-in
cases and carry that kind (see ``README.md``, "Adding examples").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

HERE = Path(__file__).resolve().parent
EXAMPLES_PATH = HERE / "naturalistic_examples.jsonl"
JUDGE_RUN_PATH = HERE / "naturalistic_judge_run.json"
QUEUE_PATH = HERE / "naturalistic_adjudication_queue.jsonl"

Decision = Literal["estimate", "needs_clarification"]
Difficulty = Literal["unambiguous", "inferable", "indeterminate"]
Provenance = Literal["authored", "judged", "contested"]
Sampling = Literal["unanimous", "jitter", "flip", "divergent", "unanimous_ask", "consistent_wrong"]

# Deterministic guessed portions for divergent/consistent-wrong indeterminate
# samples — the same factor-of-two shape as the synthetic band's
# (``generate_fixture.py``).
FOOD_GUESS_LOW, FOOD_GUESS_HIGH = 2.0, 4.0
EXERCISE_GUESS_LOW, EXERCISE_GUESS_HIGH = 30.0, 60.0


def _c(
    kind: str,
    name: str,
    quantity_text: str,
    amount: float | None = None,
    unit: str | None = None,
    brand: str | None = None,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {"type": kind, "name": name, "quantity_text": quantity_text}
    if amount is not None:
        candidate["amount"] = amount
    if unit is not None:
        candidate["unit"] = unit
    if brand is not None:
        candidate["brand"] = brand
    return candidate


def _ind(kind: str, name: str) -> dict[str, Any]:
    """An indeterminate candidate: named item, no recoverable quantity."""

    return {"type": kind, "name": name, "quantity_text": ""}


def _parsed_sample(parse: list[dict[str, Any]], confidence: float) -> dict[str, Any]:
    return {
        "disposition": "parsed",
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "items": parse,
    }


def _clarify_sample(parse: list[dict[str, Any]], confidence: float) -> dict[str, Any]:
    """A needs_clarification sample: same item names, no amounts, one question."""

    items = [_ind(item["type"], item["name"]) for item in parse]
    return {
        "disposition": "needs_clarification",
        "confidence": round(confidence, 2),
        "items": items,
        "clarification_questions": [
            {
                "text": "What amount did you have?",
                "options": ["1 serving", "2 servings", "3 servings"],
            }
        ],
    }


def _jitter_first_amount(parse: list[dict[str, Any]], factor: float) -> list[dict[str, Any]]:
    jittered = [dict(item) for item in parse]
    if "amount" in jittered[0]:
        jittered[0]["amount"] = round(jittered[0]["amount"] * factor, 3)
    return jittered


def _guess_parse(parse: list[dict[str, Any]], *, high: bool) -> list[dict[str, Any]]:
    """An invented-portion parse for an indeterminate input."""

    guessed: list[dict[str, Any]] = []
    for item in parse:
        if item["type"] == "exercise":
            amount = EXERCISE_GUESS_HIGH if high else EXERCISE_GUESS_LOW
            unit = "min"
        else:
            amount = FOOD_GUESS_HIGH if high else FOOD_GUESS_LOW
            unit = "serving"
        guessed.append(_c(item["type"], item["name"], f"{amount:g} {unit}", amount, unit))
    return guessed


def _samples(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a case's recorded samples from its declared ``sampling`` schedule.

    Divergence always sits inside the first sampling window (sample 2): the
    production early-stop rule skips later samples when the first window is
    unanimous, so late-only divergence would — correctly — never be observed.
    """

    schedule: Sampling = case["sampling"]
    parse = case["parse"]
    _, confidence = case["baseline"]
    if schedule == "unanimous":
        return [
            _parsed_sample(parse, confidence),
            _parsed_sample(parse, confidence - 0.02),
            _parsed_sample(parse, confidence + 0.02),
        ]
    if schedule == "jitter":
        return [
            _parsed_sample(parse, confidence),
            _parsed_sample(_jitter_first_amount(parse, 1.25), max(0.0, confidence - 0.02)),
            _parsed_sample(parse, min(1.0, confidence + 0.02)),
        ]
    if schedule == "flip":
        return [
            _parsed_sample(parse, confidence),
            _clarify_sample(parse, 0.35),
            _parsed_sample(parse, confidence),
        ]
    if schedule == "divergent":
        return [
            _parsed_sample(_guess_parse(parse, high=False), confidence),
            _clarify_sample(parse, 0.3),
            _parsed_sample(_guess_parse(parse, high=True), confidence),
        ]
    if schedule == "unanimous_ask":
        return [_clarify_sample(parse, 0.85) for _ in range(3)]
    # consistent_wrong: the model invents the *same* portion every sample —
    # self-consistency's documented blind spot.
    guess = _guess_parse(parse, high=False)
    return [
        _parsed_sample(guess, confidence),
        _parsed_sample(guess, confidence - 0.02),
        _parsed_sample(guess, confidence + 0.02),
    ]


# Each case: the authored gold label (returned by the stand-in "claude" judge)
# plus baseline (the recorded verbalized-gate stand-in) and, for judged/contested
# cases, how the stand-in "codex" label differs. Both judge outputs are authored
# here — absent an override, the codex stand-in defaults to the gold label.
#
#   provenance   codex_decision / codex_parse (override) meaning
#   authored     — (no judge run)
#   judged       agrees with gold; codex_parse optional within-tolerance jitter
#   contested    diverges; codex_decision/codex_parse describe the disagreement
_CASES: list[dict[str, Any]] = [
    # -- unambiguous: explicit quantity, but casual/typo/shorthand phrasing ----
    {
        "difficulty": "unambiguous",
        "template": "casual_explicit",
        "input": "had 2 eggs n a slice of wheat toast this morning",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [
            _c("food", "eggs", "2", 2.0, "count"),
            _c("food", "wheat toast", "a slice", 1.0, "slice"),
        ],
        "baseline": ("parsed", 0.82),
        "provenance": "judged",
    },
    {
        "difficulty": "unambiguous",
        "template": "brand_shorthand",
        "input": "1 tbsp kraft PB on a rice cake",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [
            _c("food", "peanut butter", "1 tbsp", 1.0, "tbsp", brand="Kraft"),
            _c("food", "rice cake", "1", 1.0, "count"),
        ],
        "baseline": ("parsed", 0.74),
        "provenance": "judged",
        "codex_parse": [
            _c("food", "peanut butter", "1 tbsp", 1.0, "tbsp", brand="Kraft"),
            _c("food", "rice cake", "1", 1.0, "count"),
        ],
    },
    {
        "difficulty": "unambiguous",
        "template": "typo_measure",
        "input": "170g greek yoghurt + a drizzle of honey",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [
            _c("food", "greek yogurt", "170g", 170.0, "g"),
            _c("food", "honey", "a drizzle", 1.0, "tsp"),
        ],
        "baseline": ("parsed", 0.8),
        "provenance": "judged",
        # codex lands 180g — within the 20% amount tolerance, still agreement.
        "codex_parse": [
            _c("food", "greek yogurt", "180g", 180.0, "g"),
            _c("food", "honey", "a drizzle", 1.0, "tsp"),
        ],
    },
    {
        "difficulty": "unambiguous",
        "template": "casual_explicit",
        "input": "ran 5k then a 20 min cooldown walk",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [
            _c("exercise", "run", "5k", 5.0, "km"),
            _c("exercise", "walk", "20 min", 20.0, "min"),
        ],
        "baseline": ("parsed", 0.86),
        "provenance": "judged",
    },
    {
        "difficulty": "unambiguous",
        "template": "casual_explicit",
        "input": "grande oat milk latte, 16oz",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [_c("food", "oat milk latte", "16oz", 16.0, "oz")],
        "baseline": ("parsed", 0.71),
        "provenance": "authored",
    },
    {
        "difficulty": "unambiguous",
        "template": "typo_measure",
        "input": "chicken breast ~150 g grilled, no oil",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [_c("food", "chicken breast", "~150 g", 150.0, "g")],
        "baseline": ("parsed", 0.83),
        "provenance": "authored",
    },
    {
        "difficulty": "unambiguous",
        "template": "multi_item",
        "input": "2 slices pepperoni pizza and a can of coke",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [
            _c("food", "pepperoni pizza", "2 slices", 2.0, "slice"),
            _c("food", "coke", "a can", 1.0, "can", brand="Coca-Cola"),
        ],
        "baseline": ("parsed", 0.77),
        "provenance": "authored",
    },
    {
        "difficulty": "unambiguous",
        "template": "casual_explicit",
        "input": "did 45 mins on the elliptical at the gym",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [_c("exercise", "elliptical", "45 mins", 45.0, "min")],
        "baseline": ("parsed", 0.88),
        "provenance": "authored",
    },
    # -- inferable: structure implies a typical portion (estimate-first) --------
    {
        "difficulty": "inferable",
        "template": "casual_range",
        "input": "had a handful (5-10) of deep fried onion rings",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [_c("food", "onion rings", "5-10", 7.5, "count")],
        # baseline over-asks: the old verbalized gate goes low on a hedged range.
        "baseline": ("needs_clarification", 0.34),
        "provenance": "judged",
    },
    {
        "difficulty": "inferable",
        "template": "brand_shorthand",
        "input": "3 PB cracker sandwiches",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [
            _c("food", "crackers", "6", 6.0, "count"),
            _c("food", "peanut butter", "about 1 tbsp each", 3.0, "tbsp"),
        ],
        "baseline": ("parsed", 0.52),
        "provenance": "judged",
    },
    {
        "difficulty": "inferable",
        "template": "count_plus_household_volume",
        "input": "6 crackers with about 1.5-2 tbsp dill pickle hummus",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [
            _c("food", "crackers", "6", 6.0, "count"),
            _c("food", "dill pickle hummus", "about 1.5-2 tbsp", 1.75, "tbsp"),
        ],
        "baseline": ("parsed", 0.59),
        "provenance": "authored",
    },
    {
        "difficulty": "inferable",
        "template": "casual_hedge",
        "input": "a bowl of cereal w/ milk, prob a normal serving",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [
            _c("food", "cereal", "a bowl", 1.0, "bowl"),
            _c("food", "milk", "a splash", 0.5, "cup"),
        ],
        "baseline": ("needs_clarification", 0.4),
        "provenance": "judged",
        "codex_parse": [
            _c("food", "cereal", "a bowl", 1.0, "bowl"),
            _c("food", "milk", "a splash", 0.5, "cup"),
        ],
    },
    {
        "difficulty": "inferable",
        "template": "casual_range",
        "input": "grabbed like 2-3 slices of cheese",
        "sampling": "jitter",
        "decision": "estimate",
        "parse": [_c("food", "cheese", "2-3 slices", 2.5, "slice")],
        "baseline": ("parsed", 0.58),
        "provenance": "judged",
        # codex reads 2 slices flat; 2.0 vs 2.5 is within the 20% tolerance.
        "codex_parse": [_c("food", "cheese", "2 slices", 2.0, "slice")],
    },
    {
        "difficulty": "inferable",
        "template": "casual_hedge",
        "input": "half a leftover burrito for lunch",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [_c("food", "burrito", "half", 0.5, "burrito")],
        "baseline": ("parsed", 0.63),
        "provenance": "authored",
    },
    {
        "difficulty": "inferable",
        "template": "casual_range",
        "input": "played 3 games of badminton after work",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [_c("exercise", "badminton", "3 games", 3.0, "game")],
        "baseline": ("needs_clarification", 0.37),
        "provenance": "authored",
    },
    {
        "difficulty": "inferable",
        "template": "brand_shorthand",
        "input": "a clif bar on the drive over",
        "sampling": "unanimous",
        "decision": "estimate",
        "parse": [_c("food", "protein bar", "1 bar", 1.0, "bar", brand="Clif")],
        "baseline": ("parsed", 0.6),
        "provenance": "authored",
    },
    {
        "difficulty": "inferable",
        "template": "casual_hedge",
        "input": "a couple scoops of vanilla ice cream",
        "sampling": "jitter",
        "decision": "estimate",
        "parse": [_c("food", "ice cream", "a couple scoops", 2.0, "scoop")],
        "baseline": ("parsed", 0.55),
        "provenance": "authored",
    },
    {
        "difficulty": "inferable",
        "template": "casual_hedge",
        "input": "big salad with grilled chicken and some ranch",
        "sampling": "flip",
        "decision": "estimate",
        "parse": [
            _c("food", "salad", "big", 1.0, "serving"),
            _c("food", "grilled chicken", "some", 1.0, "serving"),
            _c("food", "ranch dressing", "some", 2.0, "tbsp"),
        ],
        "baseline": ("needs_clarification", 0.42),
        "provenance": "authored",
    },
    # -- indeterminate: named item, amount not recoverable → ask ---------------
    {
        "difficulty": "indeterminate",
        "template": "bare_items",
        "input": "crackers and peanut butter",
        "sampling": "divergent",
        "decision": "needs_clarification",
        "parse": [_ind("food", "crackers"), _ind("food", "peanut butter")],
        "baseline": ("needs_clarification", 0.22),
        "provenance": "judged",
    },
    {
        "difficulty": "indeterminate",
        "template": "leftovers",
        "input": "some leftover thai curry",
        "sampling": "divergent",
        "decision": "needs_clarification",
        "parse": [_ind("food", "thai curry")],
        "baseline": ("needs_clarification", 0.28),
        "provenance": "judged",
    },
    {
        "difficulty": "indeterminate",
        "template": "vague_snack",
        "input": "snacked on chips while watching tv",
        "sampling": "unanimous_ask",
        "decision": "needs_clarification",
        "parse": [_ind("food", "chips")],
        "baseline": ("needs_clarification", 0.25),
        "provenance": "judged",
        # codex also asks — a needs_clarification pair agrees on the decision.
        "codex_decision": "needs_clarification",
        "codex_parse": [_ind("food", "chips")],
    },
    {
        "difficulty": "indeterminate",
        "template": "vague_exercise",
        "input": "worked out at the gym",
        "sampling": "divergent",
        "decision": "needs_clarification",
        "parse": [_ind("exercise", "workout")],
        "baseline": ("needs_clarification", 0.3),
        "provenance": "judged",
    },
    {
        "difficulty": "indeterminate",
        "template": "bare_items",
        "input": "rice and chicken for dinner",
        "sampling": "divergent",
        "decision": "needs_clarification",
        "parse": [_ind("food", "rice"), _ind("food", "chicken")],
        "baseline": ("needs_clarification", 0.24),
        "provenance": "authored",
    },
    {
        "difficulty": "indeterminate",
        "template": "vague_snack",
        "input": "handful of trail mix",
        "sampling": "consistent_wrong",
        "decision": "needs_clarification",
        "parse": [_ind("food", "trail mix")],
        "baseline": ("needs_clarification", 0.33),
        "provenance": "authored",
    },
    {
        "difficulty": "indeterminate",
        "template": "leftovers",
        "input": "grazed on cheese and crackers at the party",
        "sampling": "unanimous_ask",
        "decision": "needs_clarification",
        "parse": [_ind("food", "cheese"), _ind("food", "crackers")],
        "baseline": ("needs_clarification", 0.21),
        "provenance": "authored",
    },
    {
        "difficulty": "indeterminate",
        "template": "vague_exercise",
        "input": "went for a bike ride",
        "sampling": "divergent",
        "decision": "needs_clarification",
        "parse": [_ind("exercise", "cycling")],
        "baseline": ("needs_clarification", 0.29),
        "provenance": "authored",
    },
    # -- contested: judges disagree → queue, NOT committed to the seed ---------
    {
        "difficulty": "inferable",
        "template": "casual_hedge",
        "input": "some pasta with a bit of sauce",
        "decision": "estimate",
        "parse": [
            _c("food", "pasta", "some", 1.0, "serving"),
            _c("food", "sauce", "a bit", 0.5, "cup"),
        ],
        "baseline": ("needs_clarification", 0.36),
        "provenance": "contested",
        # Genuine borderline: codex judges the portion indeterminate and asks.
        "codex_decision": "needs_clarification",
        "codex_parse": [_ind("food", "pasta"), _ind("food", "sauce")],
    },
    {
        "difficulty": "inferable",
        "template": "casual_hedge",
        "input": "a few beers last night",
        "decision": "estimate",
        "parse": [_c("food", "beer", "a few", 3.0, "bottle")],
        "baseline": ("parsed", 0.5),
        "provenance": "contested",
        # Both estimate, but the portion is a factor of two apart (3 vs 6):
        # outside the amount tolerance, so it is genuinely contestable.
        "codex_decision": "estimate",
        "codex_parse": [_c("food", "beer", "a few", 6.0, "bottle")],
    },
]


def _example_record(index: int, case: dict[str, Any]) -> dict[str, Any]:
    # "recorded_stand_in", never "cross_provider_judge": these labels were
    # authored alongside their stand-in judge outputs, not produced by a live
    # judge run (see the module docstring).
    source_kind = (
        "authored_naturalistic" if case["provenance"] == "authored" else "recorded_stand_in"
    )
    disposition, confidence = case["baseline"]
    return {
        "id": f"naturalistic-{index:03d}",
        "difficulty": case["difficulty"],
        "band": "naturalistic",
        "source_kind": source_kind,
        "source_template": case["template"],
        "input": case["input"],
        "gold_decision": case["decision"],
        "gold_parse": case["parse"],
        "baseline": {"disposition": disposition, "confidence": round(confidence, 2)},
        "samples": _samples(case),
    }


def _judge_label(decision: Decision, parse: list[dict[str, Any]]) -> dict[str, Any]:
    return {"gold_decision": decision, "gold_parse": parse}


def _judge_run_record(case: dict[str, Any]) -> dict[str, Any]:
    claude = _judge_label(case["decision"], case["parse"])
    codex = _judge_label(
        case.get("codex_decision", case["decision"]),
        case.get("codex_parse", case["parse"]),
    )
    return {"input": case["input"], "claude": claude, "codex": codex}


def build() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (committed examples, judge-run records, queue entries)."""

    examples: list[dict[str, Any]] = []
    judge_records: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []

    committed = [case for case in _CASES if case["provenance"] != "contested"]
    for offset, case in enumerate(committed, start=1):
        examples.append(_example_record(offset, case))

    for case in _CASES:
        if case["provenance"] in {"judged", "contested"}:
            judge_records.append(_judge_run_record(case))
        if case["provenance"] == "contested":
            claude = _judge_label(case["decision"], case["parse"])
            codex = _judge_label(
                case.get("codex_decision", case["decision"]),
                case.get("codex_parse", case["parse"]),
            )
            reason = (
                f"decision: claude={case['decision']}, codex={case['codex_decision']}"
                if case.get("codex_decision", case["decision"]) != case["decision"]
                else "estimate: judges disagree on items or portions"
            )
            queue.append(
                {"input": case["input"], "reason": reason, "claude": claude, "codex": codex}
            )

    return examples, judge_records, queue


def main() -> int:
    examples, judge_records, queue = build()
    EXAMPLES_PATH.write_text(
        "".join(json.dumps(example, sort_keys=True) + "\n" for example in examples),
        encoding="utf-8",
    )
    judge_run = {
        "protocol_version": 1,
        "note": (
            "Author-constructed stand-in judge outputs used to build and verify "
            "the naturalistic seed offline (a deterministic router-regression "
            "fixture, mirroring FTY-158's recorded samples). No live judge "
            "produced these labels — the matching seed rows carry source_kind "
            "recorded_stand_in, never cross_provider_judge. NOT real user data "
            "and NOT a claim of specific live model output; the maintainer's "
            "live run (tests.parse_calibration.judge) replaces it."
        ),
        "records": judge_records,
    }
    JUDGE_RUN_PATH.write_text(
        json.dumps(judge_run, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    QUEUE_PATH.write_text(
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in queue),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

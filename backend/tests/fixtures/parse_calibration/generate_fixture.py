"""Generate the committed synthetic parse calibration fixture.

The generator is deterministic and builds every natural-language input from a
known parse plus a known estimate/ask label. It intentionally uses only synthetic
food/exercise phrases and writes no private user data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

Decision = Literal["estimate", "needs_clarification"]
Difficulty = Literal["unambiguous", "inferable", "indeterminate"]

HERE = Path(__file__).resolve().parent
EXAMPLES_PATH = HERE / "examples.jsonl"


def main() -> int:
    examples = build_examples()
    EXAMPLES_PATH.write_text(
        "".join(json.dumps(example, sort_keys=True) + "\n" for example in examples),
        encoding="utf-8",
    )
    return 0


def build_examples() -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    examples.extend(_unambiguous_examples())
    examples.extend(_inferable_examples())
    examples.extend(_indeterminate_examples())
    return examples


def _unambiguous_examples() -> list[dict[str, Any]]:
    foods = [
        ("eggs", "2", 2.0, "count"),
        ("banana", "1", 1.0, "count"),
        ("Greek yogurt", "170 g", 170.0, "g"),
        ("white rice", "1 cup", 1.0, "cup"),
        ("apple", "1 medium", 1.0, "medium"),
        ("chicken breast", "150 g", 150.0, "g"),
        ("black coffee", "12 oz", 12.0, "oz"),
        ("almonds", "28 g", 28.0, "g"),
        ("oatmeal", "40 g", 40.0, "g"),
        ("cheddar cheese", "1 slice", 1.0, "slice"),
    ]
    exercises = [
        ("run", "30 min", 30.0, "min"),
        ("walk", "45 min", 45.0, "min"),
        ("cycle", "25 min", 25.0, "min"),
        ("yoga", "40 min", 40.0, "min"),
        ("strength training", "50 min", 50.0, "min"),
        ("swim", "20 min", 20.0, "min"),
        ("row", "15 min", 15.0, "min"),
        ("hike", "90 min", 90.0, "min"),
        ("elliptical", "35 min", 35.0, "min"),
        ("stairs", "10 min", 10.0, "min"),
    ]
    examples: list[dict[str, Any]] = []
    for index in range(50):
        name, quantity, amount, unit = foods[index % len(foods)]
        examples.append(
            _record(
                index=index + 1,
                difficulty="unambiguous",
                template="explicit_food",
                text=f"{quantity} {name}",
                decision="estimate",
                parse=[_candidate("food", name, quantity, amount, unit)],
                baseline_confidence=_confidence(index, base=0.93, low_every=23),
            )
        )
    for index in range(50):
        exercise, quantity, amount, unit = exercises[index % len(exercises)]
        food_name, food_quantity, food_amount, food_unit = foods[(index + 3) % len(foods)]
        examples.append(
            _record(
                index=index + 51,
                difficulty="unambiguous",
                template="explicit_food_and_exercise",
                text=f"{food_quantity} {food_name} and {quantity} {exercise}",
                decision="estimate",
                parse=[
                    _candidate("food", food_name, food_quantity, food_amount, food_unit),
                    _candidate("exercise", exercise, quantity, amount, unit),
                ],
                baseline_confidence=_confidence(index, base=0.9, low_every=29),
            )
        )
    return examples


def _inferable_examples() -> list[dict[str, Any]]:
    contexts = [
        "",
        " for breakfast",
        " for lunch",
        " for dinner",
        " after practice",
        " at home",
        " at work",
        " tonight",
        " this morning",
        " after class",
    ]
    cases = [
        (
            "a bowl of oatmeal",
            [_candidate("food", "oatmeal", "a bowl", 1.0, "bowl")],
        ),
        (
            "a handful of almonds",
            [_candidate("food", "almonds", "a handful", 1.0, "handful")],
        ),
        (
            "one peanut butter sandwich",
            [
                _candidate("food", "bread", "2 slices", 2.0, "slice"),
                _candidate("food", "peanut butter", "about 2 tbsp", 2.0, "tbsp"),
            ],
        ),
        (
            "a slice of pizza",
            [_candidate("food", "pizza", "a slice", 1.0, "slice")],
        ),
        (
            "a mug of coffee with milk",
            [
                _candidate("food", "coffee", "a mug", 1.0, "mug"),
                _candidate("food", "milk", "splash", 1.0, "splash"),
            ],
        ),
        (
            "half a burrito",
            [_candidate("food", "burrito", "half", 0.5, "burrito")],
        ),
        (
            "3 crackers with peanut butter",
            [
                _candidate("food", "crackers", "3", 3.0, "crackers"),
                _candidate("food", "peanut butter", "about 1 tbsp", 1.0, "tbsp"),
            ],
        ),
        (
            "a salad with dressing",
            [
                _candidate("food", "salad", "a salad", 1.0, "serving"),
                _candidate("food", "dressing", "drizzle", 1.0, "tbsp"),
            ],
        ),
        (
            "a protein bar",
            [_candidate("food", "protein bar", "1 bar", 1.0, "bar")],
        ),
        (
            "a glass of orange juice",
            [_candidate("food", "orange juice", "a glass", 1.0, "glass")],
        ),
    ]
    examples: list[dict[str, Any]] = []
    for index in range(100):
        text, parse = cases[index % len(cases)]
        context = contexts[index // len(cases)]
        examples.append(
            _record(
                index=index + 1,
                difficulty="inferable",
                template="estimate_first_structure",
                text=f"{text}{context}",
                decision="estimate",
                parse=parse,
                baseline_confidence=_confidence(index, base=0.68, low_every=5),
            )
        )
    return examples


def _indeterminate_examples() -> list[dict[str, Any]]:
    contexts = [
        "",
        " for breakfast",
        " for lunch",
        " for dinner",
        " after practice",
        " at home",
        " at work",
        " tonight",
        " this morning",
        " after class",
    ]
    cases = [
        ("crackers and peanut butter", ["crackers", "peanut butter"], "food"),
        ("rice and chicken", ["rice", "chicken"], "food"),
        ("pasta with sauce", ["pasta", "sauce"], "food"),
        ("trail mix", ["trail mix"], "food"),
        ("cereal and milk", ["cereal", "milk"], "food"),
        ("chips", ["chips"], "food"),
        ("leftover curry", ["curry"], "food"),
        ("ice cream", ["ice cream"], "food"),
        ("went for a run", ["run"], "exercise"),
        ("did some cycling", ["cycling"], "exercise"),
    ]
    examples: list[dict[str, Any]] = []
    for index in range(100):
        text, names, kind = cases[index % len(cases)]
        context = contexts[index // len(cases)]
        baseline_confidence = _indeterminate_baseline_confidence(index)
        examples.append(
            _record(
                index=index + 1,
                difficulty="indeterminate",
                template="missing_amount_or_duration",
                text=f"{text}{context}",
                decision="needs_clarification",
                parse=[_candidate(kind, name, "") for name in names],
                baseline_confidence=baseline_confidence,
                baseline_disposition=(
                    "parsed" if baseline_confidence >= 0.45 else "needs_clarification"
                ),
            )
        )
    return examples


def _record(
    *,
    index: int,
    difficulty: Difficulty,
    template: str,
    text: str,
    decision: Decision,
    parse: list[dict[str, Any]],
    baseline_confidence: float,
    baseline_disposition: str = "parsed",
) -> dict[str, Any]:
    return {
        "id": f"{difficulty}-{index:03d}",
        "difficulty": difficulty,
        "source_kind": "synthetic_by_construction",
        "source_template": template,
        "input": text,
        "gold_decision": decision,
        "gold_parse": parse,
        "baseline": {
            "disposition": baseline_disposition,
            "confidence": round(baseline_confidence, 2),
        },
    }


def _candidate(
    kind: str,
    name: str,
    quantity_text: str,
    amount: float | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "type": kind,
        "name": name,
        "quantity_text": quantity_text,
    }
    if amount is not None:
        candidate["amount"] = amount
    if unit is not None:
        candidate["unit"] = unit
    return candidate


def _confidence(index: int, *, base: float, low_every: int) -> float:
    if index % low_every == low_every - 1:
        return 0.38
    return max(0.0, min(1.0, base - (index % 7) * 0.03))


def _indeterminate_baseline_confidence(index: int) -> float:
    if index % 8 == 0:
        return 0.62
    if index % 11 == 0:
        return 0.49
    return 0.22


if __name__ == "__main__":
    raise SystemExit(main())

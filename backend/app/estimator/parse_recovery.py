"""Bounded recovery for common parse-provider schema-shape mistakes (FTY-300).

Provider output remains untrusted until it validates as :class:`ParseResult`.
This module handles only explicitly enumerated, mechanical shape mistakes before
that validation: harmless wrapper objects, enum casing, ``None`` for optional
arrays, and numeric strings in numeric fields. It never stores or logs raw model
output, and unrecoverable replies raise the same content-free validation error as
the strict path.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, ClassVar

from pydantic import ConfigDict, ValidationError, model_validator

from app.llm.errors import StructuredOutputValidationError
from app.schemas.parse import ParseResult

_WRAPPER_KEYS = frozenset({"parse_result", "result", "response", "output"})
_LIST_FIELDS = frozenset({"items", "clarification_questions"})
_TOP_LEVEL_NUMERIC_FIELDS = frozenset({"confidence"})
_ITEM_NUMERIC_FIELDS = frozenset(
    {
        "amount",
        "stated_calories",
        "stated_protein_g",
        "stated_carbs_g",
        "stated_fat_g",
    }
)


def recoverable_parse_result_schema(max_repair_attempts: int) -> type[ParseResult]:
    """Return a ``ParseResult`` schema with bounded pre-validation recovery.

    The provider contract remains ``structured_completion(prompt, schema)``:
    callers pass this ParseResult-compatible schema, the provider performs its
    normal retry and validation flow, and the schema's before-validator handles
    only deterministic shape repair before Pydantic enforces the real schema.
    """

    return _recoverable_parse_result_schema(max(0, max_repair_attempts))


@lru_cache(maxsize=16)
def _recoverable_parse_result_schema(max_repair_attempts: int) -> type[ParseResult]:
    class RecoverableParseResult(ParseResult):
        model_config = ConfigDict(extra="forbid", title="ParseResult")

        _max_repair_attempts: ClassVar[int] = max_repair_attempts

        @model_validator(mode="before")
        @classmethod
        def _apply_recovery(cls, value: Any) -> Any:
            return repair_parse_result_payload(
                value,
                max_repair_attempts=cls._max_repair_attempts,
            )

    RecoverableParseResult.__name__ = "ParseResult"
    RecoverableParseResult.__qualname__ = "ParseResult"
    return RecoverableParseResult


def validate_parse_result(raw: Any, *, max_repair_attempts: int) -> ParseResult:
    """Validate ``raw`` as ``ParseResult`` after bounded mechanical recovery.

    The first pass is the normal strict schema boundary. If it fails, at most
    ``max_repair_attempts`` deterministic repair passes run. Each pass either
    unwraps one harmless wrapper object or normalizes known field shapes once;
    there is no provider retry and no loop that can depend on model output.
    """

    repaired = repair_parse_result_payload(raw, max_repair_attempts=max_repair_attempts)
    try:
        return ParseResult.model_validate(repaired)
    except ValidationError:
        pass

    raise StructuredOutputValidationError(
        "provider output failed validation against ParseResult"
    ) from None


def repair_parse_result_payload(raw: Any, *, max_repair_attempts: int) -> Any:
    """Return ``raw`` or a mechanically repaired payload for ParseResult validation."""

    try:
        ParseResult.model_validate(raw)
    except ValidationError:
        current: Any = raw
    else:
        return raw

    for _ in range(max(0, max_repair_attempts)):
        repaired = _repair_once(current)
        if repaired == current:
            break
        try:
            ParseResult.model_validate(repaired)
        except ValidationError:
            current = repaired
        else:
            return repaired

    return current


def _repair_once(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value

    unwrapped = _unwrap_harmless_wrapper(value)
    if unwrapped is not value:
        return unwrapped

    repaired: dict[str, Any] = dict(value)
    if "disposition" in repaired:
        repaired["disposition"] = _normalize_token(repaired["disposition"])
    for field in _LIST_FIELDS:
        if repaired.get(field) is None:
            repaired[field] = []
    for field in _TOP_LEVEL_NUMERIC_FIELDS:
        if field in repaired:
            repaired[field] = _numeric_value(repaired[field])

    items = repaired.get("items")
    if isinstance(items, list):
        repaired["items"] = [_repair_item(item) for item in items]

    return repaired


def _unwrap_harmless_wrapper(value: Mapping[str, Any]) -> Any:
    if len(value) != 1:
        return value
    key, wrapped = next(iter(value.items()))
    if key in _WRAPPER_KEYS and isinstance(wrapped, Mapping):
        return dict(wrapped)
    return value


def _repair_item(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    item = dict(value)
    if "type" in item:
        item["type"] = _normalize_token(item["type"])
    for field in _ITEM_NUMERIC_FIELDS:
        if field in item:
            item[field] = _numeric_value(item[field])
    return item


def _normalize_token(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


def _numeric_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip().replace(",", "")
    if not text:
        return value
    try:
        parsed = float(text)
    except ValueError:
        return value
    if not math.isfinite(parsed):
        return value
    return parsed

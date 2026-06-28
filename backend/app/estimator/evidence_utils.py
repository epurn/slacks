"""Shared evidence helpers for the estimator pipeline (FTY-082).

Canonical implementations of the two helpers used across every estimator step
that touches evidence: the content fingerprint and the source-ref recorder.
A single copy here prevents silent divergence between multiple independent
definitions (which could produce mismatched fingerprints across evidence tiers).
"""

from __future__ import annotations

import hashlib

from app.estimator.food_serving import NutritionFacts
from app.estimator.pipeline import EstimationContext


def _content_hash(source_ref: str, facts: NutritionFacts) -> str:
    """A reproducible fingerprint of the canonical facts (no user data)."""

    canonical = f"{source_ref}|{facts.calories}|{facts.protein_g}|{facts.carbs_g}|{facts.fat_g}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_source_ref(context: EstimationContext, source: str) -> None:
    """Record a consulted source system as run evidence (content-free metadata)."""

    if source not in context.source_refs:
        context.source_refs.append(source)

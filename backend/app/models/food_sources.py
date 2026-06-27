"""Global source-fact cache and per-resolution evidence models (FTY-044).

Generic-food resolution (FTY-044) writes two kinds of source-backed rows, kept
deliberately separate per ``docs/security/data-retention.md`` and the contract
principle that *global source facts must not contain user-specific habits*:

- ``products`` — a **global** cache of nutrition facts retrieved from a trusted
  source (USDA FDC). It carries **no** ``user_id``: the per-100g facts for "white
  rice" are the same for everyone, so caching them avoids repeat external lookups.
  Keyed by ``(source, query_key)``; retained as global source facts (no user data to
  delete).
- ``evidence_sources`` — the **user-owned** provenance record for one resolved
  ``derived_food_items`` row: which source backed it, the content hash, when it was
  fetched, and an immutable snapshot of the per-100g facts used. It carries
  ``user_id`` and ``log_event_id`` with ``ON DELETE CASCADE`` so it is deleted with
  the owning log event, user, or account. Raw pages are never stored — only the
  source reference, hash, timestamp, and extracted facts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class Product(Base):
    """A cached, global generic-food nutrition fact from a trusted source.

    No ``user_id``: these are global source facts (per-100g calories/macros) shared
    across all users, cached to avoid repeat external lookups. ``query_key`` is the
    normalized food name that retrieved it (the cache key) and ``source_ref`` the
    stable source id (``usda_fdc:<fdcId>``). ``content_hash`` fingerprints the facts.
    """

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("source", "query_key", name="uq_products_source_query"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    #: Source system identifier, e.g. ``usda_fdc``.
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Stable per-record source reference, e.g. ``usda_fdc:171688``.
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Normalized food name that produced this cache entry (the lookup key).
    query_key: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    #: Canonical per-100g facts: kcal energy and macros in grams.
    calories_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    protein_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    #: Source default serving in grams, when known; enables count-based quantities.
    default_serving_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class EvidenceSource(Base):
    """User-owned provenance for one resolved derived food item.

    Records which trusted source backed a user's food resolution, the content hash,
    the fetch timestamp, and an immutable snapshot of the per-100g facts used — never
    the raw page. ``user_id`` and ``log_event_id`` carry object-level ownership with
    ``ON DELETE CASCADE``; ``product_id`` links to the global cache row and is
    ``SET NULL`` so clearing the cache never deletes a user's evidence.
    """

    __tablename__ = "evidence_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    log_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("log_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    derived_food_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("derived_food_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Source-hierarchy classification, e.g. ``trusted_nutrition_database``.
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Stable per-record source reference, e.g. ``usda_fdc:171688``.
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Immutable snapshot of the per-100g facts used for this resolution.
    calories_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    protein_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

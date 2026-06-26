"""ORM models for the canonical identity and profile data model (FTY-020).

Importing this package registers every model on :data:`app.db.Base.metadata`,
which Alembic's migration environment uses as autogenerate/target metadata.
"""

from __future__ import annotations

from app.models.identity import AuthIdentity, User, UserProfile

__all__ = ["AuthIdentity", "User", "UserProfile"]

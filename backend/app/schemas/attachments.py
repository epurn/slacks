"""Log-attachment boundary DTO + upload constraints (FTY-077).

Two things cross the attachment boundary:

- the **upload constraints** — the allowed image content-types and the maximum
  byte size — which :mod:`app.services.attachments` enforces fail-closed before any
  bytes are stored or handed onward; and
- :class:`LogAttachmentDTO` — the metadata view of a saved attachment, returned so
  a client can describe, retrieve, and delete the image. It deliberately omits the
  raw image bytes: the bytes are served separately, never embedded in JSON.

The constants live here (not buried in the service) so the contract — what counts
as an acceptable upload — is explicit and testable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

#: Maximum accepted upload size in bytes (10 MiB). A nutrition-label photo from a
#: phone fits comfortably; anything larger is rejected fail-closed before storage.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

#: The image content-types the upload path accepts. Anything else is rejected
#: deterministically; the allowlist (not a blocklist) is the fail-closed default.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})


class LogAttachmentDTO(BaseModel):
    """Metadata view of a saved attachment (no raw bytes).

    Carries everything a client needs to identify, describe, and delete the saved
    image; the image bytes themselves are served through a separate path.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    log_event_id: uuid.UUID
    content_type: str
    byte_size: int
    content_hash: str
    created_at: datetime
    updated_at: datetime

"""Envelope contract — the only shape connectors produce.

Envelope IDs are **content-addressed**: same record content → same UUID. This
makes raw-lake landing idempotent end-to-end. INSERT OR IGNORE on `envelopes`
silently drops re-syncs of unchanged records, and the JSONL writer skips disk
writes when the SQLite insert was a no-op.

When the underlying record genuinely changes (e.g., order status moves from
pending → paid), the payload hash changes, so a *new* envelope row is written.
That's exactly the desired behavior: the lake records one row per real change,
not one row per fetch.
"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

_NAMESPACE = UUID("d2c00000-0000-0000-0000-000000000000")


def content_envelope_id(
    merchant_id: str,
    source: str,
    source_object_type: str,
    source_object_id: str,
    payload: dict[str, Any],
) -> UUID:
    """Compute a content-addressed envelope_id.

    Same (merchant, source, type, source_id, payload) → same UUID. JSON is
    canonicalized (sorted keys, no whitespace) so trivial formatting changes
    in the source response don't fork the envelope.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    key = f"{merchant_id}|{source}|{source_object_type}|{source_object_id}|{canonical}"
    return uuid5(_NAMESPACE, key)


class Envelope(BaseModel):
    """Connectors wrap every record in this envelope before landing in the raw lake.

    Source-faithful: original payload preserved verbatim. All interpretation
    happens later in projections, which can be re-run as logic evolves.
    """

    model_config = ConfigDict(frozen=True)

    envelope_id: UUID
    merchant_id: str
    source: str
    source_version: str
    connector_version: str
    source_object_type: str
    source_object_id: str
    source_event_type: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_updated_at: datetime | None = None
    payload: dict[str, Any]

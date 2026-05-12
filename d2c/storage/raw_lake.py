"""Raw lake landing — append-only, idempotent.

Disk: <raw_lake_dir>/<merchant>/<source>/<YYYY-MM-DD>.jsonl
DB:   row in `envelopes` indexed by content-addressed envelope_id.

Idempotency contract:
- envelope_id is a hash of (merchant, source, type, source_id, payload).
- INSERT OR IGNORE on envelopes — same content → no insert.
- JSONL append happens ONLY when the insert was new, so disk doesn't bloat
  on re-sync of unchanged records.
- Order: insert first, then append on success, then commit. If the append
  raises, the transaction is rolled back — file and DB stay consistent.
"""

import json
import sqlite3
from pathlib import Path

from d2c.envelope import Envelope


def land(conn: sqlite3.Connection, raw_lake_dir: Path, envelope: Envelope) -> bool:
    """Land an envelope idempotently. Returns True if it was new, False if a
    duplicate (same content-addressed envelope_id already on file)."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO envelopes (
            envelope_id, merchant_id, source, source_version, connector_version,
            source_object_type, source_object_id, source_event_type,
            fetched_at, source_updated_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(envelope.envelope_id),
            envelope.merchant_id,
            envelope.source,
            envelope.source_version,
            envelope.connector_version,
            envelope.source_object_type,
            envelope.source_object_id,
            envelope.source_event_type,
            envelope.fetched_at.isoformat(),
            envelope.source_updated_at.isoformat() if envelope.source_updated_at else None,
            json.dumps(envelope.payload),
        ),
    )
    if cur.rowcount == 0:
        # Duplicate — already on disk and indexed. No-op.
        return False

    fetched_date = envelope.fetched_at.date().isoformat()
    file_path = (
        raw_lake_dir / envelope.merchant_id / envelope.source / f"{fetched_date}.jsonl"
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a") as f:
        f.write(envelope.model_dump_json() + "\n")

    conn.commit()
    return True

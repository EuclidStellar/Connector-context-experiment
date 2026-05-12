"""Shared projection helpers."""

import json
import sqlite3
from typing import Any


def latest_envelopes(
    conn: sqlite3.Connection,
    merchant_id: str,
    source: str,
    object_type: str,
) -> list[dict[str, Any]]:
    """Return the most recent envelope per source_object_id for a (merchant, source, type)."""
    rows = conn.execute(
        """
        SELECT envelope_id, source_object_id, payload_json, fetched_at
          FROM envelopes
         WHERE merchant_id = ? AND source = ? AND source_object_type = ?
         ORDER BY source_object_id, fetched_at DESC
        """,
        (merchant_id, source, object_type),
    ).fetchall()
    latest: dict[str, sqlite3.Row] = {}
    for r in rows:
        if r["source_object_id"] not in latest:
            latest[r["source_object_id"]] = r
    return [
        {
            "envelope_id": r["envelope_id"],
            "source_object_id": r["source_object_id"],
            "payload": json.loads(r["payload_json"]),
        }
        for r in latest.values()
    ]

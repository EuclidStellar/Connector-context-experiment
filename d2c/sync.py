import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from d2c.config import MerchantConfig
from d2c.connectors.base import Connector
from d2c.connectors.klaviyo import KlaviyoConnector
from d2c.connectors.razorpay import RazorpayConnector
from d2c.connectors.shopify import ShopifyConnector
from d2c.storage import raw_lake

CONNECTOR_REGISTRY: dict[str, type[Connector]] = {
    "shopify": ShopifyConnector,
    "razorpay": RazorpayConnector,
    "klaviyo": KlaviyoConnector,
}


def sync_one(
    merchant_config: MerchantConfig,
    source: str,
    raw_lake_dir: Path,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Sync one source for one merchant. Returns counts per object_type."""
    if source not in CONNECTOR_REGISTRY:
        raise ValueError(f"Unknown source: {source}")

    connector_cfg = merchant_config.connectors.get(source, {})
    if not connector_cfg.get("enabled", True):
        return {"skipped": True}

    connector_class = CONNECTOR_REGISTRY[source]
    connector = connector_class(
        merchant_id=merchant_config.merchant_id,
        config=connector_cfg,
        secrets=merchant_config.secrets,
    )

    since = _read_cursor(conn, merchant_config.merchant_id, source)
    started_at = datetime.now(timezone.utc)

    counts: dict[str, int] = {}
    skipped: dict[str, int] = {}
    last_updated_per_type: dict[str, datetime] = {}

    for envelope in connector.poll(since):
        is_new = raw_lake.land(conn, raw_lake_dir, envelope)
        if is_new:
            counts[envelope.source_object_type] = (
                counts.get(envelope.source_object_type, 0) + 1
            )
        else:
            skipped[envelope.source_object_type] = (
                skipped.get(envelope.source_object_type, 0) + 1
            )
        if envelope.source_updated_at:
            prev = last_updated_per_type.get(envelope.source_object_type)
            if prev is None or envelope.source_updated_at > prev:
                last_updated_per_type[envelope.source_object_type] = (
                    envelope.source_updated_at
                )

    for object_type, max_updated in last_updated_per_type.items():
        _write_cursor(
            conn,
            merchant_config.merchant_id,
            source,
            object_type,
            max_updated,
            started_at,
        )

    return {"new": counts, "skipped": skipped}


def _read_cursor(
    conn: sqlite3.Connection, merchant_id: str, source: str
) -> datetime | None:
    # Conservative cursor: read the EARLIEST per-object cursor for this source,
    # so a single poll(since=...) covers any partial-progress state. INSERT OR
    # IGNORE on envelopes makes the over-fetch idempotent.
    rows = conn.execute(
        "SELECT cursor_value FROM sync_cursors WHERE merchant_id = ? AND source = ?",
        (merchant_id, source),
    ).fetchall()
    if not rows:
        return None
    values = [
        datetime.fromisoformat(r["cursor_value"]) for r in rows if r["cursor_value"]
    ]
    return min(values) if values else None


def _write_cursor(
    conn: sqlite3.Connection,
    merchant_id: str,
    source: str,
    object_type: str,
    cursor_value: datetime,
    last_sync_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO sync_cursors (merchant_id, source, object_type, cursor_value, last_sync_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(merchant_id, source, object_type) DO UPDATE SET
            cursor_value = excluded.cursor_value,
            last_sync_at = excluded.last_sync_at
        """,
        (
            merchant_id,
            source,
            object_type,
            cursor_value.isoformat(),
            last_sync_at.isoformat(),
        ),
    )
    conn.commit()

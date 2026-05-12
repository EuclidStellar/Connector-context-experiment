"""Sensory tools — direct access to the canonical store with provenance.

Every result carries citations pointing back to the source envelope so any
downstream claim is reconstructible.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from d2c.projections.shopify import PROJECTION_VERSION
from d2c.projections.klaviyo import PROJECTION_VERSION as KLAVIYO_PROJECTION_VERSION


def get_customer_journey(
    conn: sqlite3.Connection,
    merchant_id: str,
    customer_canonical_id: str | None = None,
    email: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """Return the full chronological multi-source timeline for one customer.

    Either canonical_id or email can identify the customer; email is resolved
    against the canonical customers table. Returns orders + email engagement
    events interleaved by time, each with its own citation.
    """
    if not customer_canonical_id and not email:
        return {
            "value": None,
            "citations": [],
            "reasoning": "Provide either customer_canonical_id or email.",
        }

    if email and not customer_canonical_id:
        row = conn.execute(
            """
            SELECT canonical_id, email FROM customers
             WHERE merchant_id = ?
               AND projection_version = ?
               AND email = ?
             LIMIT 1
            """,
            (merchant_id, PROJECTION_VERSION, email),
        ).fetchone()
        if not row:
            return {
                "value": None,
                "citations": [],
                "reasoning": f"No canonical customer with email {email!r}.",
            }
        customer_canonical_id = row["canonical_id"]

    # Pull customer header for context.
    customer = conn.execute(
        """
        SELECT canonical_id, email, phone, first_seen_at, derived_from_envelope_id
          FROM customers
         WHERE merchant_id = ?
           AND projection_version = ?
           AND canonical_id = ?
         LIMIT 1
        """,
        (merchant_id, PROJECTION_VERSION, customer_canonical_id),
    ).fetchone()
    if not customer:
        return {
            "value": None,
            "citations": [],
            "reasoning": f"No customer with canonical_id {customer_canonical_id!r}.",
        }

    # Pull aggregate lifetime stats so the agent has context without recompute.
    stats = conn.execute(
        """
        SELECT COUNT(*) AS order_count,
               COALESCE(SUM(net_revenue), 0) AS lifetime_net_revenue,
               COALESCE(SUM(settled_revenue), 0) AS lifetime_settled_revenue,
               MIN(placed_at) AS first_order_at,
               MAX(placed_at) AS last_order_at
          FROM orders
         WHERE merchant_id = ? AND projection_version = ? AND customer_canonical_id = ?
        """,
        (merchant_id, PROJECTION_VERSION, customer_canonical_id),
    ).fetchone()

    # Orders timeline.
    order_rows = conn.execute(
        """
        SELECT 'order' AS kind, placed_at AS occurred_at,
               derived_from_envelope_id AS envelope_id, order_number AS ref,
               gross_revenue, total_discount, net_revenue, settled_revenue,
               currency, status, NULL AS channel, NULL AS state
          FROM orders
         WHERE merchant_id = ? AND projection_version = ? AND customer_canonical_id = ?
        """,
        (merchant_id, PROJECTION_VERSION, customer_canonical_id),
    ).fetchall()

    # Email engagement timeline.
    msg_rows = conn.execute(
        """
        SELECT 'message' AS kind, sent_at AS occurred_at,
               derived_from_envelope_id AS envelope_id, NULL AS ref,
               NULL AS gross_revenue, NULL AS total_discount, NULL AS net_revenue,
               NULL AS settled_revenue, NULL AS currency, NULL AS status,
               channel, state
          FROM messages
         WHERE merchant_id = ? AND projection_version = ? AND customer_canonical_id = ?
        """,
        (merchant_id, KLAVIYO_PROJECTION_VERSION, customer_canonical_id),
    ).fetchall()

    combined = list(order_rows) + list(msg_rows)
    combined.sort(key=lambda r: r["occurred_at"] or "", reverse=True)
    timeline = combined[:limit]

    events: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for r in timeline:
        events.append(
            {
                "kind": r["kind"],
                "occurred_at": r["occurred_at"],
                "envelope_id": r["envelope_id"],
                "ref": r["ref"],
                "gross_revenue": r["gross_revenue"],
                "net_revenue": r["net_revenue"],
                "settled_revenue": r["settled_revenue"],
                "currency": r["currency"],
                "status": r["status"],
                "channel": r["channel"],
                "state": r["state"],
            }
        )
        citations.append(
            {
                "envelope_id": r["envelope_id"],
                "source": "shopify" if r["kind"] == "order" else "klaviyo",
                "ref": (
                    f"order/{r['ref']}" if r["kind"] == "order" else f"message/{r['state']}"
                ),
            }
        )

    citations.append(
        {
            "envelope_id": customer["derived_from_envelope_id"],
            "source": "shopify",
            "ref": f"customer/{customer['canonical_id'][:8]}",
        }
    )

    return {
        "value": {
            "customer": {
                "canonical_id": customer["canonical_id"],
                "email": customer["email"],
                "phone": customer["phone"],
                "first_seen_at": customer["first_seen_at"],
            },
            "lifetime_stats": {
                "order_count": stats["order_count"],
                "net_revenue": stats["lifetime_net_revenue"],
                "settled_revenue": stats["lifetime_settled_revenue"],
                "first_order_at": stats["first_order_at"],
                "last_order_at": stats["last_order_at"],
            },
            "timeline": events,
            "timeline_size": len(events),
        },
        "citations": citations,
        "reasoning": (
            f"Customer {customer['email']}: {stats['order_count']} orders, "
            f"net lifetime {stats['lifetime_net_revenue']:.2f}, "
            f"first {stats['first_order_at'] or 'never'}, "
            f"last {stats['last_order_at'] or 'never'}. "
            f"Timeline shows {len(events)} most recent event(s) across orders and email."
        ),
    }


def get_recent_orders(
    conn: sqlite3.Connection,
    merchant_id: str,
    days_back: int = 7,
    limit: int = 50,
) -> dict[str, Any]:
    """List orders placed within the last `days_back` days for a merchant."""
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    rows = conn.execute(
        """
        SELECT order_number, placed_at, gross_revenue, total_discount,
               total_tax, total_shipping, net_revenue, currency, status,
               customer_canonical_id, derived_from_envelope_id
          FROM orders
         WHERE merchant_id = ?
           AND projection_version = ?
           AND placed_at >= ?
         ORDER BY placed_at DESC
         LIMIT ?
        """,
        (merchant_id, PROJECTION_VERSION, since.isoformat(), limit),
    ).fetchall()

    orders: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for r in rows:
        orders.append(
            {
                "order_number": r["order_number"],
                "placed_at": r["placed_at"],
                "gross_revenue": r["gross_revenue"],
                "total_discount": r["total_discount"],
                "total_tax": r["total_tax"],
                "total_shipping": r["total_shipping"],
                "net_revenue": r["net_revenue"],
                "currency": r["currency"],
                "status": r["status"],
                "customer_canonical_id": r["customer_canonical_id"],
                "envelope_id": r["derived_from_envelope_id"],
            }
        )
        citations.append(
            {
                "envelope_id": r["derived_from_envelope_id"],
                "source": "shopify",
                "ref": f"order/{r['order_number']}",
            }
        )

    return {
        "value": orders,
        "citations": citations,
        "summary": f"{len(orders)} orders in the last {days_back} day(s)",
    }

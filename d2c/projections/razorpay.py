"""Razorpay projection: updates orders.settled_revenue on matching Shopify rows.

The match is by Razorpay's notes.shopify_order_number → canonical Shopify
orders.order_number. v0 keeps this as an UPDATE on the existing canonical
row rather than maintaining a separate payment_reconciliations table. The
Razorpay envelope is recoverable from the envelopes table at query time
when the reconciliation tool needs to cite it.
"""

import sqlite3
from typing import Any

from d2c.projections.common import latest_envelopes

PROJECTION_VERSION = "razorpay-v1"


def project_all(conn: sqlite3.Connection, merchant_id: str) -> dict[str, int]:
    return {"orders_settled": project_orders(conn, merchant_id)}


def project_orders(conn: sqlite3.Connection, merchant_id: str) -> int:
    envelopes = latest_envelopes(conn, merchant_id, "razorpay", "order")
    n_updated = 0
    n_unmatched = 0
    for env in envelopes:
        p = env["payload"]
        notes = p.get("notes") or {}
        shopify_order_number = notes.get("shopify_order_number")
        if not shopify_order_number:
            continue
        amount_paise = p.get("amount", 0) or 0
        amount_rupees = float(amount_paise) / 100.0

        cur = conn.execute(
            """
            UPDATE orders
               SET settled_revenue = ?
             WHERE merchant_id = ?
               AND projection_version = 'shopify-v1'
               AND order_number = ?
            """,
            (amount_rupees, merchant_id, str(shopify_order_number)),
        )
        if cur.rowcount > 0:
            n_updated += 1
        else:
            n_unmatched += 1
    conn.commit()
    if n_unmatched:
        # Soft warning — surface but don't fail. A Razorpay order with a
        # shopify_order_number that doesn't match any canonical Shopify order
        # could mean the Shopify projection hasn't run yet, or the order was
        # deleted on the Shopify side.
        print(
            f"  warning: {n_unmatched} Razorpay orders had a shopify_order_number "
            f"that didn't match any canonical Shopify order."
        )
    return n_updated

"""Shopify projections: latest envelope per source_object_id → canonical rows.

Every derived row carries:
  - derived_from_envelope_id (provenance back to source bytes)
  - projection_version (lazy re-projection — multiple versions can coexist)

Canonical IDs are deterministic via UUID5 over (merchant_id, source, entity,
source_id). Re-running the projection produces the same canonical_ids, so
INSERT OR REPLACE is idempotent.
"""

import json
import sqlite3
import uuid
from typing import Any

from d2c.projections.common import latest_envelopes

PROJECTION_VERSION = "shopify-v1"

# Stable namespace so canonical IDs are deterministic across runs.
_NAMESPACE = uuid.UUID("d2c00000-0000-0000-0000-000000000000")


def _canonical_id(merchant_id: str, source: str, entity: str, source_id: str) -> str:
    key = f"{merchant_id}|{source}|{entity}|{source_id}"
    return str(uuid.uuid5(_NAMESPACE, key))


def project_all(conn: sqlite3.Connection, merchant_id: str) -> dict[str, int]:
    return {
        "customers": project_customers(conn, merchant_id),
        "products": project_products(conn, merchant_id),
        "orders": project_orders(conn, merchant_id),
    }


def project_customers(conn: sqlite3.Connection, merchant_id: str) -> int:
    envelopes = latest_envelopes(conn, merchant_id, "shopify", "customer")
    for env in envelopes:
        p = env["payload"]
        canonical_id = _canonical_id(
            merchant_id, "shopify", "customer", env["source_object_id"]
        )
        # Shopify dev stores scrub PII (email/phone/name) unless the custom
        # app has been granted "Protected customer data" access. Synthesize
        # a stable address from the Shopify customer id so identity merging
        # still works across sources. Synthetic addresses use the .local TLD
        # to make their nature obvious.
        real_email = p.get("email")
        email = real_email or f"customer-{env['source_object_id']}@seeded.local"
        aliases = [
            {"source": "shopify", "source_id": env["source_object_id"], "type": "id"},
            {"source": "shopify", "source_id": email, "type": "email"},
        ]
        conn.execute(
            """
            INSERT OR REPLACE INTO customers (
                canonical_id, merchant_id, derived_from_envelope_id, projection_version,
                aliases_json, email, phone, first_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_id,
                merchant_id,
                env["envelope_id"],
                PROJECTION_VERSION,
                json.dumps(aliases),
                email,
                p.get("phone"),
                p.get("created_at"),
            ),
        )
    conn.commit()
    return len(envelopes)


def project_products(conn: sqlite3.Connection, merchant_id: str) -> int:
    envelopes = latest_envelopes(conn, merchant_id, "shopify", "product")
    for env in envelopes:
        p = env["payload"]
        canonical_id = _canonical_id(
            merchant_id, "shopify", "product", env["source_object_id"]
        )
        variants = p.get("variants", [])
        sku = variants[0].get("sku") if variants else None
        if not sku:
            sku = f"PROD-{env['source_object_id']}"
        conn.execute(
            """
            INSERT OR REPLACE INTO products (
                canonical_id, merchant_id, derived_from_envelope_id, projection_version,
                sku, title, attributes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_id,
                merchant_id,
                env["envelope_id"],
                PROJECTION_VERSION,
                sku,
                p.get("title"),
                json.dumps(
                    {"product_type": p.get("product_type"), "tags": p.get("tags")}
                ),
            ),
        )
    conn.commit()
    return len(envelopes)


def project_orders(conn: sqlite3.Connection, merchant_id: str) -> int:
    envelopes = latest_envelopes(conn, merchant_id, "shopify", "order")
    for env in envelopes:
        p = env["payload"]
        order_canonical_id = _canonical_id(
            merchant_id, "shopify", "order", env["source_object_id"]
        )

        customer_data = p.get("customer") or {}
        customer_canonical_id = None
        if customer_data.get("id"):
            customer_canonical_id = _canonical_id(
                merchant_id, "shopify", "customer", str(customer_data["id"])
            )

        # Shopify revenue accounting:
        #  - subtotal_price = items total AFTER item-level discounts but BEFORE order-level
        #  - total_discounts = order-level discount (the percentage we applied)
        #  - total_price = subtotal + tax + shipping - order discounts
        # gross_revenue here = what items "should" cost ignoring our promotional discount.
        total_discount = float(p.get("total_discounts", "0") or 0)
        total_tax = float(p.get("total_tax", "0") or 0)
        shipping_lines = p.get("shipping_lines", [])
        total_shipping = sum(
            float(s.get("price", "0") or 0) for s in shipping_lines
        )
        subtotal = float(p.get("subtotal_price", "0") or 0)
        gross_revenue = subtotal + total_discount
        # net = what customer paid for the goods (excluding tax/shipping)
        total_price = float(p.get("total_price", "0") or 0)
        net_revenue = total_price - total_tax - total_shipping

        # Use ON CONFLICT instead of INSERT OR REPLACE so re-running this
        # projection does NOT blast settled_revenue (which Razorpay owns).
        # Shopify owns: gross_revenue, total_*, net_revenue, currency, status,
        # placed_at, customer link, order_number. settled_revenue is preserved.
        conn.execute(
            """
            INSERT INTO orders (
                canonical_id, merchant_id, derived_from_envelope_id, projection_version,
                customer_canonical_id, order_number, placed_at,
                gross_revenue, total_discount, total_tax, total_shipping,
                net_revenue, settled_revenue, currency, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_id, projection_version) DO UPDATE SET
                derived_from_envelope_id = excluded.derived_from_envelope_id,
                customer_canonical_id    = excluded.customer_canonical_id,
                order_number             = excluded.order_number,
                placed_at                = excluded.placed_at,
                gross_revenue            = excluded.gross_revenue,
                total_discount           = excluded.total_discount,
                total_tax                = excluded.total_tax,
                total_shipping           = excluded.total_shipping,
                net_revenue              = excluded.net_revenue,
                currency                 = excluded.currency,
                status                   = excluded.status
                -- settled_revenue intentionally NOT updated (Razorpay owns it)
            """,
            (
                order_canonical_id,
                merchant_id,
                env["envelope_id"],
                PROJECTION_VERSION,
                customer_canonical_id,
                str(p.get("order_number") or p.get("name", "")),
                p.get("created_at", ""),
                gross_revenue,
                total_discount,
                total_tax,
                total_shipping,
                net_revenue,
                None,  # settled_revenue lands from Razorpay projection
                p.get("currency", "INR"),
                p.get("financial_status"),
            ),
        )

        # Re-project line items: delete existing, re-insert. Cheaper than diffing.
        conn.execute(
            "DELETE FROM order_lines WHERE order_canonical_id = ? AND projection_version = ?",
            (order_canonical_id, PROJECTION_VERSION),
        )
        for line in p.get("line_items", []):
            line_canonical_id = _canonical_id(
                merchant_id, "shopify", "order_line", str(line["id"])
            )
            product_canonical_id = None
            if line.get("product_id"):
                product_canonical_id = _canonical_id(
                    merchant_id, "shopify", "product", str(line["product_id"])
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO order_lines (
                    canonical_id, merchant_id, derived_from_envelope_id, projection_version,
                    order_canonical_id, product_canonical_id, quantity, unit_price, discount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    line_canonical_id,
                    merchant_id,
                    env["envelope_id"],
                    PROJECTION_VERSION,
                    order_canonical_id,
                    product_canonical_id,
                    int(line.get("quantity", 1)),
                    float(line.get("price", "0") or 0),
                    float(line.get("total_discount", "0") or 0),
                ),
            )
    conn.commit()
    return len(envelopes)

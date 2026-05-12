"""Seed Razorpay orders paired with existing Shopify orders.

For each canonical Shopify order, creates a Razorpay order with the Shopify
order_number in notes. Most pair cleanly (settled = Shopify net). A minority
intentionally settle for less — simulating refunds that didn't propagate to
Shopify. That gap is the reconciliation demo signal the watcher should find.
"""

import random
import sqlite3
import time
from typing import Any

import httpx

from d2c.config import MerchantConfig

# 15% of orders get a synthetic settlement gap (5%-30% under Shopify net).
GAP_PROBABILITY = 0.15
GAP_MIN_PCT = 0.05
GAP_MAX_PCT = 0.30


class RazorpayOrderSeeder:
    def __init__(self, merchant_config: MerchantConfig, conn: sqlite3.Connection):
        self.merchant_id = merchant_config.merchant_id
        self.key_id = merchant_config.secret("RAZORPAY_KEY_ID")
        self.key_secret = merchant_config.secret("RAZORPAY_KEY_SECRET")
        self.conn = conn
        self.client = httpx.Client(
            auth=(self.key_id, self.key_secret),
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

    def close(self) -> None:
        self.client.close()

    def _shopify_orders(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT order_number, net_revenue, currency
              FROM orders
             WHERE merchant_id = ?
               AND projection_version = 'shopify-v1'
               AND net_revenue IS NOT NULL
               AND net_revenue > 0
            """,
            (self.merchant_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _already_seeded(self, shopify_order_number: str) -> bool:
        # Skip Shopify orders that already have a paired Razorpay envelope.
        row = self.conn.execute(
            """
            SELECT 1 FROM envelopes
             WHERE merchant_id = ?
               AND source = 'razorpay'
               AND source_object_type = 'order'
               AND json_extract(payload_json, '$.notes.shopify_order_number') = ?
             LIMIT 1
            """,
            (self.merchant_id, str(shopify_order_number)),
        ).fetchone()
        return row is not None

    def seed_from_shopify(self) -> dict[str, int]:
        shopify_orders = self._shopify_orders()
        if not shopify_orders:
            raise RuntimeError(
                "No canonical Shopify orders found. Run `d2c project default --source shopify` first."
            )

        results: dict[str, int] = {"created": 0, "skipped": 0, "errors": 0, "with_gap": 0}
        for so in shopify_orders:
            if self._already_seeded(so["order_number"]):
                results["skipped"] += 1
                continue

            currency = so["currency"] or "INR"
            # Razorpay currency must be ISO 4217. Treat dev-store USD as INR for v0
            # so the test API accepts the order; the demo storyline is unaffected.
            if currency == "USD":
                currency = "INR"

            net_revenue = float(so["net_revenue"])
            has_gap = random.random() < GAP_PROBABILITY
            if has_gap:
                gap_pct = random.uniform(GAP_MIN_PCT, GAP_MAX_PCT)
                settled = net_revenue * (1 - gap_pct)
            else:
                settled = net_revenue

            amount_paise = int(round(settled * 100))
            if amount_paise < 100:  # Razorpay rejects orders under ₹1
                amount_paise = 100

            body = {
                "amount": amount_paise,
                "currency": currency,
                "receipt": f"shopify-{so['order_number']}",
                "notes": {
                    "shopify_order_number": str(so["order_number"]),
                    "merchant_id": self.merchant_id,
                    "seeded_gap": "true" if has_gap else "false",
                },
            }
            try:
                r = self.client.post("https://api.razorpay.com/v1/orders", json=body)
                r.raise_for_status()
                results["created"] += 1
                if has_gap:
                    results["with_gap"] += 1
            except httpx.HTTPStatusError as e:
                results["errors"] += 1
                print(
                    f"  shopify#{so['order_number']} failed: "
                    f"{e.response.status_code} {e.response.text[:200]}"
                )
            time.sleep(0.1)  # gentle throttle; test mode has generous limits
        return results

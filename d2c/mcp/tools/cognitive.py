"""Cognitive tools — D2C-specific computations the LLM should NOT do in its head.

These are where the moat lives: opinionated analyses returned as structured,
citable results so the LLM only paraphrases (with citations).
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from d2c.projections.klaviyo import PROJECTION_VERSION as KLAVIYO_PROJECTION_VERSION
from d2c.projections.shopify import PROJECTION_VERSION


def find_engaged_non_buyers(
    conn: sqlite3.Connection,
    merchant_id: str,
    window_days: int = 30,
    min_engagements: int = 2,
    limit: int = 10,
) -> dict[str, Any]:
    """Customers who've opened/clicked emails but haven't placed an order in the window.

    The "warm but not converting" signal. These are the people a founder
    might want to reach out to personally or hit with a targeted offer —
    interest exists, the friction is between click and checkout.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    rows = conn.execute(
        """
        SELECT c.canonical_id, c.email, c.derived_from_envelope_id AS customer_envelope_id,
               COUNT(DISTINCT CASE
                     WHEN m.state IN ('opened', 'clicked') AND m.sent_at >= ?
                     THEN m.canonical_id END) AS engagements,
               MAX(CASE WHEN m.state IN ('opened', 'clicked') THEN m.sent_at END)
                     AS last_engagement_at,
               (SELECT COUNT(*) FROM orders o
                  WHERE o.customer_canonical_id = c.canonical_id
                    AND o.projection_version = ?
                    AND o.placed_at >= ?) AS orders_in_window,
               (SELECT COUNT(*) FROM orders o
                  WHERE o.customer_canonical_id = c.canonical_id
                    AND o.projection_version = ?) AS lifetime_order_count,
               (SELECT MAX(placed_at) FROM orders o
                  WHERE o.customer_canonical_id = c.canonical_id
                    AND o.projection_version = ?) AS last_order_at
          FROM customers c
          LEFT JOIN messages m ON m.customer_canonical_id = c.canonical_id
                              AND m.projection_version = ?
         WHERE c.merchant_id = ?
           AND c.projection_version = ?
         GROUP BY c.canonical_id
        HAVING engagements >= ? AND orders_in_window = 0
         ORDER BY engagements DESC
         LIMIT ?
        """,
        (
            since,
            PROJECTION_VERSION,
            since,
            PROJECTION_VERSION,
            PROJECTION_VERSION,
            KLAVIYO_PROJECTION_VERSION,
            merchant_id,
            PROJECTION_VERSION,
            min_engagements,
            limit,
        ),
    ).fetchall()

    if not rows:
        return {
            "value": [],
            "citations": [],
            "reasoning": (
                f"No customers found with ≥{min_engagements} email engagements but zero "
                f"orders in the last {window_days} day(s). Either everyone engaged is "
                f"buying, or there's not enough engagement data to surface a gap."
            ),
        }

    customers: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for r in rows:
        customers.append(
            {
                "email": r["email"],
                "canonical_id": r["canonical_id"],
                "engagements_in_window": r["engagements"],
                "last_engagement_at": r["last_engagement_at"],
                "orders_in_window": r["orders_in_window"],
                "lifetime_order_count": r["lifetime_order_count"],
                "last_order_at": r["last_order_at"],
            }
        )
        citations.append(
            {
                "envelope_id": r["customer_envelope_id"],
                "source": "shopify",
                "ref": f"customer/{r['canonical_id'][:8]}",
            }
        )

    return {
        "value": customers,
        "citations": citations,
        "reasoning": (
            f"Found {len(customers)} engaged non-buyer(s) in the last {window_days} day(s). "
            f"Top: {customers[0]['email']} with {customers[0]['engagements_in_window']} "
            f"email engagement(s) and 0 orders this window "
            f"({customers[0]['lifetime_order_count']} lifetime orders)."
        ),
    }


def find_lapsed_high_value_customers(
    conn: sqlite3.Connection,
    merchant_id: str,
    lapsed_days: int = 60,
    min_lifetime_value: float = 1000.0,
    limit: int = 10,
) -> dict[str, Any]:
    """High-LTV customers who haven't placed an order in `lapsed_days`.

    Win-back targets. A founder asking "who left me?" should get this list —
    sorted by what they're worth, with their last interaction surfaced.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lapsed_days)).isoformat()
    rows = conn.execute(
        """
        WITH customer_stats AS (
            SELECT customer_canonical_id,
                   COALESCE(SUM(net_revenue), 0) AS lifetime_value,
                   COUNT(*) AS order_count,
                   MAX(placed_at) AS last_order_at,
                   MAX(derived_from_envelope_id) AS last_order_envelope_id
              FROM orders
             WHERE merchant_id = ?
               AND projection_version = ?
               AND customer_canonical_id IS NOT NULL
             GROUP BY customer_canonical_id
        )
        SELECT c.canonical_id, c.email, cs.lifetime_value, cs.order_count,
               cs.last_order_at, cs.last_order_envelope_id,
               c.derived_from_envelope_id AS customer_envelope_id
          FROM customer_stats cs
          JOIN customers c
            ON c.canonical_id = cs.customer_canonical_id
           AND c.projection_version = ?
         WHERE cs.lifetime_value >= ?
           AND cs.last_order_at < ?
         ORDER BY cs.lifetime_value DESC
         LIMIT ?
        """,
        (
            merchant_id,
            PROJECTION_VERSION,
            PROJECTION_VERSION,
            min_lifetime_value,
            cutoff,
            limit,
        ),
    ).fetchall()

    if not rows:
        return {
            "value": [],
            "citations": [],
            "reasoning": (
                f"No customers with lifetime value ≥ {min_lifetime_value:.2f} have "
                f"lapsed beyond {lapsed_days} days. Either the high-value cohort is "
                f"still active, or this merchant is too new for a meaningful lapse window."
            ),
        }

    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for r in rows:
        try:
            last_dt = datetime.fromisoformat(r["last_order_at"].replace("Z", "+00:00"))
            days_since = (now - last_dt).days
        except Exception:
            days_since = None
        out.append(
            {
                "email": r["email"],
                "canonical_id": r["canonical_id"],
                "lifetime_value": r["lifetime_value"],
                "order_count": r["order_count"],
                "last_order_at": r["last_order_at"],
                "days_since_last_order": days_since,
            }
        )
        citations.append(
            {
                "envelope_id": r["last_order_envelope_id"],
                "source": "shopify",
                "ref": f"last-order/{r['canonical_id'][:8]}",
            }
        )

    return {
        "value": out,
        "citations": citations,
        "reasoning": (
            f"Found {len(out)} high-value customer(s) (LTV ≥ {min_lifetime_value:.2f}) "
            f"lapsed > {lapsed_days} days. Top: {out[0]['email']} with lifetime value "
            f"{out[0]['lifetime_value']:.2f}, last ordered "
            f"{out[0]['days_since_last_order']} day(s) ago."
        ),
    }


def find_top_customers_by_ltv(
    conn: sqlite3.Connection,
    merchant_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Top customers ranked by lifetime net revenue.

    The VIP list — who actually keeps the lights on. A founder should know
    these by name; this tool makes that table fall out of the data.
    """
    rows = conn.execute(
        """
        SELECT c.canonical_id, c.email, c.derived_from_envelope_id AS customer_envelope_id,
               COALESCE(SUM(o.net_revenue), 0) AS lifetime_value,
               COALESCE(SUM(o.settled_revenue), 0) AS lifetime_settled,
               COUNT(o.canonical_id) AS order_count,
               MAX(o.placed_at) AS last_order_at,
               MAX(o.derived_from_envelope_id) AS last_order_envelope_id
          FROM customers c
          LEFT JOIN orders o
                 ON o.customer_canonical_id = c.canonical_id
                AND o.projection_version = ?
         WHERE c.merchant_id = ?
           AND c.projection_version = ?
         GROUP BY c.canonical_id
        HAVING lifetime_value > 0
         ORDER BY lifetime_value DESC
         LIMIT ?
        """,
        (PROJECTION_VERSION, merchant_id, PROJECTION_VERSION, limit),
    ).fetchall()

    if not rows:
        return {
            "value": [],
            "citations": [],
            "reasoning": "No customers with revenue. Possibly an empty merchant.",
        }

    out: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "email": r["email"],
                "canonical_id": r["canonical_id"],
                "lifetime_value": r["lifetime_value"],
                "lifetime_settled": r["lifetime_settled"],
                "order_count": r["order_count"],
                "last_order_at": r["last_order_at"],
            }
        )
        citations.append(
            {
                "envelope_id": r["last_order_envelope_id"] or r["customer_envelope_id"],
                "source": "shopify",
                "ref": f"customer/{r['canonical_id'][:8]}",
            }
        )

    return {
        "value": out,
        "citations": citations,
        "reasoning": (
            f"Top {len(out)} customers by lifetime net revenue. "
            f"Leader: {out[0]['email']} at {out[0]['lifetime_value']:.2f} across "
            f"{out[0]['order_count']} orders."
        ),
    }


def compute_repeat_purchase_health(
    conn: sqlite3.Connection,
    merchant_id: str,
    cohort_days: int = 30,
    repeat_window_days: int = 60,
) -> dict[str, Any]:
    """Repeat-purchase rate for the recent cohort vs the prior cohort.

    Two cohorts: customers whose FIRST order fell in the most-recent
    `cohort_days` window, vs. those in the `cohort_days` window before that.
    Repeat = placed a 2nd order within `repeat_window_days` of their first.

    Whether new customers come back is the single most load-bearing question
    for a D2C business. A decline is the loudest possible signal.
    """
    now = datetime.now(timezone.utc)
    recent_start = (now - timedelta(days=cohort_days)).isoformat()
    prior_start = (now - timedelta(days=cohort_days * 2)).isoformat()
    prior_end = recent_start

    def _cohort_stats(cohort_start: str, cohort_end: str) -> dict[str, Any]:
        rows = conn.execute(
            """
            WITH first_orders AS (
                SELECT customer_canonical_id, MIN(placed_at) AS first_at,
                       MIN(derived_from_envelope_id) AS first_envelope_id
                  FROM orders
                 WHERE merchant_id = ? AND projection_version = ?
                   AND customer_canonical_id IS NOT NULL
                 GROUP BY customer_canonical_id
            )
            SELECT fo.customer_canonical_id, fo.first_at, fo.first_envelope_id,
                   (SELECT COUNT(*) FROM orders o2
                     WHERE o2.customer_canonical_id = fo.customer_canonical_id
                       AND o2.projection_version = ?
                       AND o2.placed_at > fo.first_at) AS later_orders
              FROM first_orders fo
             WHERE fo.first_at >= ? AND fo.first_at < ?
            """,
            (
                merchant_id,
                PROJECTION_VERSION,
                PROJECTION_VERSION,
                cohort_start,
                cohort_end,
            ),
        ).fetchall()
        size = len(rows)
        repeats = sum(1 for r in rows if r["later_orders"] > 0)
        sample_envelope = rows[0]["first_envelope_id"] if rows else None
        return {
            "cohort_start": cohort_start,
            "cohort_end": cohort_end,
            "size": size,
            "repeat_buyers": repeats,
            "repeat_rate_pct": round(100.0 * repeats / size, 2) if size else 0.0,
            "sample_first_order_envelope_id": sample_envelope,
        }

    recent = _cohort_stats(recent_start, now.isoformat())
    prior = _cohort_stats(prior_start, prior_end)

    delta_pct = recent["repeat_rate_pct"] - prior["repeat_rate_pct"]

    citations: list[dict[str, Any]] = []
    for tag, c in (("recent", recent), ("prior", prior)):
        if c["sample_first_order_envelope_id"]:
            citations.append(
                {
                    "envelope_id": c["sample_first_order_envelope_id"],
                    "source": "shopify",
                    "ref": f"cohort/{tag}-first-order-sample",
                }
            )

    direction = "up" if delta_pct > 0 else "down" if delta_pct < 0 else "flat"

    return {
        "value": {
            "recent_cohort": recent,
            "prior_cohort": prior,
            "delta_pct_points": round(delta_pct, 2),
            "direction": direction,
        },
        "citations": citations,
        "reasoning": (
            f"Recent {cohort_days}d cohort: {recent['size']} new customers, "
            f"{recent['repeat_rate_pct']:.2f}% repeat. Prior cohort: "
            f"{prior['size']} new customers, {prior['repeat_rate_pct']:.2f}% repeat. "
            f"Repeat rate is {direction} {abs(delta_pct):.2f} percentage points."
        ),
    }


def find_high_aov_outliers(
    conn: sqlite3.Connection,
    merchant_id: str,
    window_days: int = 30,
    aov_multiplier: float = 3.0,
    limit: int = 5,
) -> dict[str, Any]:
    """Orders whose net revenue is `aov_multiplier`× the merchant's mean.

    Surfaces VIPs to delight and outliers to investigate (fraud, B2B order,
    bulk gift, etc.). Either way, a number worth a human glance.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    avg_row = conn.execute(
        """
        SELECT AVG(net_revenue) AS mean_aov, COUNT(*) AS n_orders
          FROM orders
         WHERE merchant_id = ? AND projection_version = ?
           AND placed_at >= ? AND net_revenue > 0
        """,
        (merchant_id, PROJECTION_VERSION, since),
    ).fetchone()
    mean_aov = avg_row["mean_aov"] or 0
    if mean_aov <= 0:
        return {
            "value": [],
            "citations": [],
            "reasoning": (
                f"Not enough order data in the last {window_days} day(s) "
                f"({avg_row['n_orders']} orders) to compute a stable mean AOV."
            ),
        }

    threshold = mean_aov * aov_multiplier
    rows = conn.execute(
        """
        SELECT order_number, placed_at, gross_revenue, total_discount,
               net_revenue, currency, status, customer_canonical_id,
               derived_from_envelope_id
          FROM orders
         WHERE merchant_id = ? AND projection_version = ?
           AND placed_at >= ?
           AND net_revenue >= ?
         ORDER BY net_revenue DESC
         LIMIT ?
        """,
        (merchant_id, PROJECTION_VERSION, since, threshold, limit),
    ).fetchall()

    if not rows:
        return {
            "value": [],
            "citations": [],
            "reasoning": (
                f"No orders ≥ {aov_multiplier}× mean AOV ({mean_aov:.2f}) in the "
                f"last {window_days} day(s). Distribution is clean."
            ),
        }

    out: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "order_number": r["order_number"],
                "placed_at": r["placed_at"],
                "net_revenue": r["net_revenue"],
                "gross_revenue": r["gross_revenue"],
                "total_discount": r["total_discount"],
                "currency": r["currency"],
                "status": r["status"],
                "aov_multiple": round(r["net_revenue"] / mean_aov, 2),
                "customer_canonical_id": r["customer_canonical_id"],
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
        "value": {
            "merchant_mean_aov": mean_aov,
            "aov_threshold": threshold,
            "outliers": out,
        },
        "citations": citations,
        "reasoning": (
            f"Mean AOV across {avg_row['n_orders']} orders in the last {window_days}d "
            f"is {mean_aov:.2f}. Surfaced {len(out)} outlier order(s) at ≥ "
            f"{aov_multiplier}× mean (threshold {threshold:.2f}). "
            f"Top: order {out[0]['order_number']} at {out[0]['net_revenue']:.2f} "
            f"({out[0]['aov_multiple']}× mean)."
        ),
    }


def find_reconciliation_gap_orders(
    conn: sqlite3.Connection,
    merchant_id: str,
    window_days: int = 30,
    min_gap_amount: float = 10.0,
    limit: int = 10,
) -> dict[str, Any]:
    """Find orders where Razorpay settled materially less than Shopify net_revenue.

    This is the cross-tool reconciliation signal: a Shopify order says "₹X paid"
    while Razorpay shows ₹Y settled — the gap is real money the founder didn't
    know was missing (refunds that didn't propagate, partial captures, etc).

    Returns the top orders by absolute gap, with citations to both the source
    Shopify envelope and the matched Razorpay envelope.
    """
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = conn.execute(
        """
        SELECT order_number, placed_at, gross_revenue, total_discount,
               net_revenue, settled_revenue, currency, status,
               derived_from_envelope_id,
               (net_revenue - settled_revenue) AS gap_amount,
               ROUND(100.0 * (net_revenue - settled_revenue) / NULLIF(net_revenue, 0), 2) AS gap_pct
          FROM orders
         WHERE merchant_id = ?
           AND projection_version = ?
           AND placed_at >= ?
           AND settled_revenue IS NOT NULL
           AND net_revenue IS NOT NULL
           AND (net_revenue - settled_revenue) >= ?
         ORDER BY (net_revenue - settled_revenue) DESC
         LIMIT ?
        """,
        (merchant_id, PROJECTION_VERSION, since.isoformat(), min_gap_amount, limit),
    ).fetchall()

    if not rows:
        # Roll up totals so the LLM can say something useful even when there's
        # nothing to flag. Coerce None → 0 so the format strings don't crash on
        # empty windows.
        totals = conn.execute(
            """
            SELECT COUNT(*) AS n_orders,
                   SUM(CASE WHEN settled_revenue IS NOT NULL THEN 1 ELSE 0 END) AS n_with_settle,
                   COALESCE(SUM(net_revenue), 0) AS total_net,
                   COALESCE(SUM(settled_revenue), 0) AS total_settled
              FROM orders
             WHERE merchant_id = ? AND projection_version = ? AND placed_at >= ?
            """,
            (merchant_id, PROJECTION_VERSION, since.isoformat()),
        ).fetchone()
        return {
            "value": [],
            "citations": [],
            "reasoning": (
                f"No reconciliation gaps ≥ {min_gap_amount} in the last {window_days} day(s). "
                f"{totals['n_with_settle'] or 0}/{totals['n_orders']} orders have settlement data; "
                f"total net {totals['total_net']:.2f} vs total settled "
                f"{totals['total_settled']:.2f}."
            ),
        }

    orders: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for r in rows:
        rzp_env = conn.execute(
            """
            SELECT envelope_id FROM envelopes
             WHERE merchant_id = ?
               AND source = 'razorpay'
               AND source_object_type = 'order'
               AND json_extract(payload_json, '$.notes.shopify_order_number') = ?
             ORDER BY fetched_at DESC LIMIT 1
            """,
            (merchant_id, str(r["order_number"])),
        ).fetchone()

        orders.append(
            {
                "order_number": r["order_number"],
                "placed_at": r["placed_at"],
                "gross_revenue": r["gross_revenue"],
                "total_discount": r["total_discount"],
                "net_revenue": r["net_revenue"],
                "settled_revenue": r["settled_revenue"],
                "gap_amount": r["gap_amount"],
                "gap_pct": r["gap_pct"],
                "currency": r["currency"],
                "status": r["status"],
                "shopify_envelope_id": r["derived_from_envelope_id"],
                "razorpay_envelope_id": rzp_env["envelope_id"] if rzp_env else None,
            }
        )
        citations.append(
            {
                "envelope_id": r["derived_from_envelope_id"],
                "source": "shopify",
                "ref": f"order/{r['order_number']}",
            }
        )
        if rzp_env:
            citations.append(
                {
                    "envelope_id": rzp_env["envelope_id"],
                    "source": "razorpay",
                    "ref": f"order/{r['order_number']}",
                }
            )

    total_gap = sum(o["gap_amount"] for o in orders if o["gap_amount"])
    return {
        "value": orders,
        "citations": citations,
        "reasoning": (
            f"Found {len(orders)} order(s) in the last {window_days} day(s) where "
            f"Razorpay settled materially less than Shopify net_revenue. "
            f"Aggregate gap: {total_gap:.2f}. Top: order {orders[0]['order_number']} "
            f"with a {orders[0]['gap_amount']:.2f} gap ({orders[0]['gap_pct']}%)."
        ),
    }


def find_largest_discount_order(
    conn: sqlite3.Connection,
    merchant_id: str,
    window_days: int = 1,
) -> dict[str, Any]:
    """Find the single order with the largest absolute discount in the window.

    Returns the order with provenance + comparative context (merchant's typical
    discount pattern) so the LLM has the ammo for a meaningful proposal.
    """
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    row = conn.execute(
        """
        SELECT order_number, placed_at, gross_revenue, total_discount,
               net_revenue, currency, status, customer_canonical_id,
               derived_from_envelope_id,
               ROUND(100.0 * total_discount / NULLIF(gross_revenue, 0), 2) AS discount_pct
          FROM orders
         WHERE merchant_id = ?
           AND projection_version = ?
           AND placed_at >= ?
           AND total_discount > 0
         ORDER BY total_discount DESC
         LIMIT 1
        """,
        (merchant_id, PROJECTION_VERSION, since.isoformat()),
    ).fetchone()

    if not row:
        return {
            "value": None,
            "citations": [],
            "reasoning": (
                f"No discount-affected orders found in the last {window_days} day(s). "
                f"Either a clean window or a different signal to investigate."
            ),
        }

    stats = conn.execute(
        """
        SELECT AVG(total_discount) AS avg_discount,
               MAX(total_discount) AS max_discount_alltime,
               COUNT(*) AS n_orders
          FROM orders
         WHERE merchant_id = ?
           AND projection_version = ?
           AND total_discount > 0
        """,
        (merchant_id, PROJECTION_VERSION),
    ).fetchone()

    return {
        "value": {
            "order_number": row["order_number"],
            "placed_at": row["placed_at"],
            "gross_revenue": row["gross_revenue"],
            "total_discount": row["total_discount"],
            "discount_pct": row["discount_pct"],
            "net_revenue": row["net_revenue"],
            "currency": row["currency"],
            "status": row["status"],
            "customer_canonical_id": row["customer_canonical_id"],
            "context": {
                "merchant_avg_discount": stats["avg_discount"],
                "merchant_max_discount_alltime": stats["max_discount_alltime"],
                "n_discounted_orders_alltime": stats["n_orders"],
            },
        },
        "citations": [
            {
                "envelope_id": row["derived_from_envelope_id"],
                "source": "shopify",
                "ref": f"order/{row['order_number']}",
            }
        ],
        "reasoning": (
            f"In the last {window_days} day(s), order {row['order_number']} carries "
            f"the largest absolute discount: {row['currency']} "
            f"{row['total_discount']:.2f} ({row['discount_pct']}% of {row['currency']} "
            f"{row['gross_revenue']:.2f} gross). Merchant-wide avg discount is "
            f"{row['currency']} {stats['avg_discount']:.2f} across "
            f"{stats['n_orders']} discounted orders."
        ),
    }

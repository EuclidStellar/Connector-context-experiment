"""MCP server: exposes the canonical store as opinionated tools to Claude Code.

Per plan §5, three layers of tools — sensory (direct lookup), cognitive
(D2C-specific computation the LLM shouldn't do), reflective (the system's
awareness of itself). Every tool returns {value, citations, ...} so any
numeric claim made downstream is reconstructible to source envelopes.

Started by Claude Code per .mcp.json; communicates over stdio.
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from d2c.mcp.tools import cognitive, reflective, sensory
from d2c.storage import db

PROJECT_ROOT = Path(__file__).parent.parent.parent

mcp = FastMCP("d2c-ai-employee")


def _conn_for(merchant_id: str):
    """Open a read-only connection for MCP tool calls.

    The MCP tools never write to the canonical store — they only query it.
    Opening with `mode=ro` prevents the bootstrap/migrate path from racing
    against concurrent writers (e.g., a running `d2c sync` or `d2c project`).
    """
    import sqlite3
    db_path = PROJECT_ROOT / "data" / merchant_id / "canonical.db"
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@mcp.tool()
def get_recent_orders(
    merchant_id: str, days_back: int = 7, limit: int = 50
) -> dict:
    """List recent orders for a merchant with provenance.

    Every order in the result links back to its source envelope via `envelope_id`
    in the row and a matching entry in the `citations` array. Cite any numeric
    claim you make from this data using the envelope_id.

    Args:
        merchant_id: which merchant to operate on (e.g., "default").
        days_back: how many days back to look. Default 7.
        limit: max number of orders to return. Default 50.
    """
    conn = _conn_for(merchant_id)
    try:
        return sensory.get_recent_orders(conn, merchant_id, days_back, limit)
    finally:
        conn.close()


@mcp.tool()
def find_largest_discount_order(
    merchant_id: str, window_days: int = 1
) -> dict:
    """Find the single order with the largest absolute discount in a window.

    Pre-computes the standout so the LLM doesn't have to reason about magnitudes
    in prose. Returns the order plus comparative context (merchant-wide
    discount average) and a citation pointing at the source envelope.

    Args:
        merchant_id: which merchant.
        window_days: how many days back to look. Default 1 (yesterday's window).
    """
    conn = _conn_for(merchant_id)
    try:
        return cognitive.find_largest_discount_order(conn, merchant_id, window_days)
    finally:
        conn.close()


@mcp.tool()
def find_engaged_non_buyers(
    merchant_id: str,
    window_days: int = 30,
    min_engagements: int = 2,
    limit: int = 10,
) -> dict:
    """Customers who opened/clicked emails but didn't buy in the window.

    The "warm but not converting" signal — high-intent prospects to personally
    reach out to or hit with a targeted offer. Cross-tool: Klaviyo engagement
    × Shopify orders. Each customer is cited via their canonical customer
    envelope; the agent can drill into get_customer_journey for full context.

    Args:
        merchant_id: which merchant.
        window_days: lookback. Default 30.
        min_engagements: minimum opens+clicks in the window. Default 2.
        limit: max customers to return. Default 10.
    """
    conn = _conn_for(merchant_id)
    try:
        return cognitive.find_engaged_non_buyers(
            conn, merchant_id, window_days, min_engagements, limit
        )
    finally:
        conn.close()


@mcp.tool()
def find_lapsed_high_value_customers(
    merchant_id: str,
    lapsed_days: int = 60,
    min_lifetime_value: float = 1000.0,
    limit: int = 10,
) -> dict:
    """High-LTV customers who haven't placed an order in `lapsed_days`.

    Win-back targets. Sorted by lifetime value so the agent leads with the
    most valuable lapses. Each customer cites the envelope of their last
    order — provenance for "they last bought on this date."

    Args:
        merchant_id: which merchant.
        lapsed_days: how stale "last order" must be to qualify. Default 60.
        min_lifetime_value: floor for qualifying as "high value." Default 1000.
        limit: max customers to return. Default 10.
    """
    conn = _conn_for(merchant_id)
    try:
        return cognitive.find_lapsed_high_value_customers(
            conn, merchant_id, lapsed_days, min_lifetime_value, limit
        )
    finally:
        conn.close()


@mcp.tool()
def find_top_customers_by_ltv(merchant_id: str, limit: int = 10) -> dict:
    """Top customers ranked by lifetime net revenue.

    The VIP list. Returns each customer with order count, lifetime net
    revenue, lifetime settled revenue (Razorpay), and last order date. Each
    cites the customer's last-order envelope.
    """
    conn = _conn_for(merchant_id)
    try:
        return cognitive.find_top_customers_by_ltv(conn, merchant_id, limit)
    finally:
        conn.close()


@mcp.tool()
def compute_repeat_purchase_health(
    merchant_id: str,
    cohort_days: int = 30,
    repeat_window_days: int = 60,
) -> dict:
    """Repeat-purchase rate for the recent cohort vs the prior cohort.

    The single most load-bearing question for a D2C business: are new
    customers coming back? Returns cohort sizes, repeat rates, and the
    direction of change (up/down/flat) in percentage points.

    Args:
        merchant_id: which merchant.
        cohort_days: cohort width AND the gap between recent vs prior. Default 30.
        repeat_window_days: not used in v0 (would tighten "within X days" repeat).
    """
    conn = _conn_for(merchant_id)
    try:
        return cognitive.compute_repeat_purchase_health(
            conn, merchant_id, cohort_days, repeat_window_days
        )
    finally:
        conn.close()


@mcp.tool()
def find_high_aov_outliers(
    merchant_id: str,
    window_days: int = 30,
    aov_multiplier: float = 3.0,
    limit: int = 5,
) -> dict:
    """Orders whose net revenue is `aov_multiplier`× the merchant's mean.

    Surfaces VIPs to delight or outliers to investigate (fraud check, B2B
    order, bulk gift). Each outlier cites the source Shopify order envelope.

    Args:
        merchant_id: which merchant.
        window_days: lookback for both the mean and the outliers. Default 30.
        aov_multiplier: how far above mean to qualify. Default 3.0.
        limit: max outliers. Default 5.
    """
    conn = _conn_for(merchant_id)
    try:
        return cognitive.find_high_aov_outliers(
            conn, merchant_id, window_days, aov_multiplier, limit
        )
    finally:
        conn.close()


@mcp.tool()
def get_customer_journey(
    merchant_id: str,
    customer_canonical_id: str | None = None,
    email: str | None = None,
    limit: int = 30,
) -> dict:
    """Full multi-source timeline for one customer.

    Orders + email engagement events interleaved by time, plus lifetime
    stats. Use this when the founder asks "tell me about <person>" or
    when a watcher proposal needs deeper context on a specific customer.
    Identify by email (resolved against canonical) or canonical_id directly.

    Args:
        merchant_id: which merchant.
        customer_canonical_id: optional canonical UUID.
        email: optional — resolves to canonical_id internally.
        limit: max events in the timeline. Default 30.
    """
    conn = _conn_for(merchant_id)
    try:
        return sensory.get_customer_journey(
            conn, merchant_id, customer_canonical_id, email, limit
        )
    finally:
        conn.close()


@mcp.tool()
def find_reconciliation_gap_orders(
    merchant_id: str,
    window_days: int = 30,
    min_gap_amount: float = 10.0,
    limit: int = 10,
) -> dict:
    """Find orders where Razorpay settled materially less than Shopify net_revenue.

    This is the cross-tool reconciliation signal. Returns the top orders by
    absolute gap, with citations to BOTH the Shopify envelope and the
    matched Razorpay envelope so the user can walk both sides of the gap.

    Args:
        merchant_id: which merchant to operate on.
        window_days: how many days back to look. Default 30.
        min_gap_amount: only return gaps at least this large (in the order's currency). Default 10.
        limit: max number of gap orders to return. Default 10.
    """
    conn = _conn_for(merchant_id)
    try:
        return cognitive.find_reconciliation_gap_orders(
            conn, merchant_id, window_days, min_gap_amount, limit
        )
    finally:
        conn.close()


@mcp.tool()
def get_trust_state(merchant_id: str) -> dict:
    """Read the current autonomy rungs per action category for this merchant.

    The reflective layer — lets the agent know what it's allowed to do, and
    what categories are structurally capped (e.g., pricing/refund are max_rung=4
    forever per the plan).
    """
    conn = _conn_for(merchant_id)
    try:
        return reflective.get_trust_state(conn, merchant_id)
    finally:
        conn.close()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

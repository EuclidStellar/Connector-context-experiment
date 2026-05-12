"""Reflective tools — the system's awareness of its own state.

Exposes the trust state, beliefs, and decision history to the LLM so the
agent can reason about what it's allowed to do and what it has already done.
"""

import sqlite3
from typing import Any


def get_trust_state(conn: sqlite3.Connection, merchant_id: str) -> dict[str, Any]:
    """Current autonomy rungs per action category for this merchant.

    Empty for v0 — categories are implicit-rung-1 (Observe) until a category
    is touched. Returns the same {value, citations} shape for consistency
    with other tools.
    """
    rows = conn.execute(
        """
        SELECT category, current_rung, max_rung, last_ratchet_at,
               last_ratchet_model_version
          FROM trust_state
         WHERE merchant_id = ?
         ORDER BY category
        """,
        (merchant_id,),
    ).fetchall()

    if not rows:
        return {
            "value": {
                "merchant_id": merchant_id,
                "categories": [],
                "note": (
                    "No trust state rows yet. All action categories are implicitly "
                    "at rung 1 (Observe) until first ratcheted. Per plan §7, "
                    "v0 caps all categories at rungs 1-4; legal-shaped categories "
                    "(pricing, refunds, customer-data deletion) carry max_rung=4 "
                    "as a structural ceiling."
                ),
            },
            "citations": [],
        }

    return {
        "value": {
            "merchant_id": merchant_id,
            "categories": [
                {
                    "category": r["category"],
                    "current_rung": r["current_rung"],
                    "max_rung": r["max_rung"],
                    "last_ratchet_at": r["last_ratchet_at"],
                    "last_ratchet_model_version": r["last_ratchet_model_version"],
                }
                for r in rows
            ],
        },
        "citations": [],
    }

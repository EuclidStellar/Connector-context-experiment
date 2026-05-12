"""Klaviyo projection: merges identity into existing customers, lands messages.

- Klaviyo profile → adds a klaviyo alias on the matched canonical customer
  (matched by email — identity resolution proper is a separate later pass).
- Klaviyo email event (Received/Opened/Clicked) → a Message row, linked back
  to the customer via the profile's email.
- All other event metrics are skipped at this projection version — they'll
  go to the Event table once we project richer signals.
"""

import json
import sqlite3
import uuid
from typing import Any

from d2c.projections.common import latest_envelopes

PROJECTION_VERSION = "klaviyo-v1"

_NAMESPACE = uuid.UUID("d2c00000-0000-0000-0000-000000000000")

EMAIL_METRIC_TO_STATE = {
    # Demo-prefixed names match the v0 seeder. The real Klaviyo system
    # metrics ("Received Email", "Opened Email", "Clicked Email") are
    # generated only by Klaviyo's email-sending infrastructure and can't be
    # POSTed via the events API — so we use custom metric names for v0 seed.
    "Demo Email Sent": "sent",
    "Demo Email Opened": "opened",
    "Demo Email Clicked": "clicked",
    # Map the real ones too so real Klaviyo-sent campaign data also projects.
    "Received Email": "sent",
    "Opened Email": "opened",
    "Clicked Email": "clicked",
}


def _canonical_id(merchant_id: str, source: str, entity: str, source_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{merchant_id}|{source}|{entity}|{source_id}"))


def project_all(conn: sqlite3.Connection, merchant_id: str) -> dict[str, int]:
    profile_result = project_profiles(conn, merchant_id)
    messages = project_email_messages(conn, merchant_id)
    return {
        "aliases_merged": profile_result["merged"],
        "customers_created": profile_result["created"],
        "messages": messages,
    }


def project_profiles(conn: sqlite3.Connection, merchant_id: str) -> dict[str, int]:
    """Project Klaviyo profiles into the canonical customers table.

    Two paths:
    - Email matches an existing canonical customer → add the klaviyo alias.
    - No match → create a new canonical customer derived from this Klaviyo
      profile. Same projection_version ('shopify-v1') so downstream queries
      treat them uniformly; the `derived_from_envelope_id` points back to
      the Klaviyo profile envelope so provenance is honest.

    This is the seam where identity resolution lives in v0 — naive email
    match. Plan §4.5's real identity-resolution pass would replace this with
    confidence-scored merging across all sources.
    """
    profile_envelopes = latest_envelopes(conn, merchant_id, "klaviyo", "profile")
    n_merged = 0
    n_created = 0
    for env in profile_envelopes:
        attrs = (env["payload"].get("attributes") or {})
        email = attrs.get("email")
        if not email:
            continue
        klaviyo_profile_id = env["source_object_id"]

        cust = conn.execute(
            """
            SELECT canonical_id, aliases_json FROM customers
             WHERE merchant_id = ?
               AND projection_version = 'shopify-v1'
               AND email = ?
             LIMIT 1
            """,
            (merchant_id, email),
        ).fetchone()

        if cust:
            existing = json.loads(cust["aliases_json"])
            if any(
                a.get("source") == "klaviyo"
                and a.get("source_id") == klaviyo_profile_id
                for a in existing
            ):
                continue
            existing.append(
                {"source": "klaviyo", "source_id": klaviyo_profile_id, "type": "id"}
            )
            conn.execute(
                """
                UPDATE customers SET aliases_json = ?
                 WHERE merchant_id = ?
                   AND canonical_id = ?
                   AND projection_version = 'shopify-v1'
                """,
                (json.dumps(existing), merchant_id, cust["canonical_id"]),
            )
            n_merged += 1
        else:
            canonical_id = _canonical_id(
                merchant_id, "klaviyo", "customer", klaviyo_profile_id
            )
            aliases = [
                {"source": "klaviyo", "source_id": klaviyo_profile_id, "type": "id"},
                {"source": "klaviyo", "source_id": email, "type": "email"},
            ]
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO customers (
                    canonical_id, merchant_id, derived_from_envelope_id, projection_version,
                    aliases_json, email, phone, first_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_id,
                    merchant_id,
                    env["envelope_id"],
                    "shopify-v1",
                    json.dumps(aliases),
                    email,
                    attrs.get("phone_number"),
                    attrs.get("created"),
                ),
            )
            if cur.rowcount > 0:
                n_created += 1
    conn.commit()
    return {"merged": n_merged, "created": n_created}


def project_email_messages(conn: sqlite3.Connection, merchant_id: str) -> int:
    # Build lookup tables from envelopes (no extra API calls; everything's local).
    metric_envelopes = latest_envelopes(conn, merchant_id, "klaviyo", "metric")
    metrics_by_id: dict[str, str | None] = {
        m["source_object_id"]: (m["payload"].get("attributes") or {}).get("name")
        for m in metric_envelopes
    }

    profile_envelopes = latest_envelopes(conn, merchant_id, "klaviyo", "profile")
    email_by_profile_id: dict[str, str | None] = {
        p["source_object_id"]: (p["payload"].get("attributes") or {}).get("email")
        for p in profile_envelopes
    }

    event_envelopes = latest_envelopes(conn, merchant_id, "klaviyo", "event")
    n = 0
    for env in event_envelopes:
        p = env["payload"]
        relationships = p.get("relationships") or {}
        metric_ref = (relationships.get("metric") or {}).get("data") or {}
        metric_id = metric_ref.get("id")
        metric_name = metrics_by_id.get(metric_id)
        if not metric_name or metric_name not in EMAIL_METRIC_TO_STATE:
            continue

        profile_ref = (relationships.get("profile") or {}).get("data") or {}
        profile_id = profile_ref.get("id")
        email = email_by_profile_id.get(profile_id) if profile_id else None
        if not email:
            continue

        cust = conn.execute(
            """
            SELECT canonical_id FROM customers
             WHERE merchant_id = ?
               AND projection_version = 'shopify-v1'
               AND email = ?
             LIMIT 1
            """,
            (merchant_id, email),
        ).fetchone()
        customer_canonical_id = cust["canonical_id"] if cust else None

        attrs = p.get("attributes") or {}
        event_time = attrs.get("datetime") or attrs.get("time")

        message_id = _canonical_id(
            merchant_id, "klaviyo", "message", env["source_object_id"]
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO messages (
                canonical_id, merchant_id, derived_from_envelope_id, projection_version,
                customer_canonical_id, channel, direction, state, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                merchant_id,
                env["envelope_id"],
                PROJECTION_VERSION,
                customer_canonical_id,
                "email",
                "outbound",
                EMAIL_METRIC_TO_STATE[metric_name],
                event_time,
            ),
        )
        n += 1
    conn.commit()
    return n

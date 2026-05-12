"""Seed Klaviyo profiles + email events for existing Shopify customers.

For each canonical Shopify customer (matched by email), creates a Klaviyo
profile and N email-engagement events (Received/Opened/Clicked) spread over
the last 30 days. Gives the projection something to write into the canonical
messages table.
"""

import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from d2c.config import MerchantConfig

# Custom metric names — Klaviyo's "Opened Email"/"Clicked Email"/etc. are
# system-managed and silently reject user-supplied events. Demo-prefixed
# names are accepted as custom metrics and round-trip through the API.
EMAIL_METRICS = ["Demo Email Sent", "Demo Email Opened", "Demo Email Clicked"]
EMAIL_WEIGHTS = [50, 35, 15]


class KlaviyoSeeder:
    def __init__(self, merchant_config: MerchantConfig, conn: sqlite3.Connection):
        self.merchant_id = merchant_config.merchant_id
        self.api_key = merchant_config.secret("KLAVIYO_PRIVATE_API_KEY")
        self.api_revision = (
            merchant_config.connectors.get("klaviyo", {}).get("api_revision", "2024-10-15")
        )
        self.conn = conn
        self.client = httpx.Client(
            headers={
                "Authorization": f"Klaviyo-API-Key {self.api_key}",
                "revision": self.api_revision,
                "accept": "application/json",
                "content-type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self.client.close()

    def _shopify_customers(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT canonical_id, email FROM customers
             WHERE merchant_id = ?
               AND projection_version = 'shopify-v1'
               AND email IS NOT NULL
               AND email != ''
            """,
            (self.merchant_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_profile(self, email: str, first_name: str | None = None) -> str | None:
        body = {
            "data": {
                "type": "profile",
                "attributes": {
                    "email": email,
                    "first_name": first_name or email.split("@")[0].title(),
                },
            }
        }
        r = self.client.post("https://a.klaviyo.com/api/profiles", json=body)
        if r.status_code == 409:
            # Already exists — Klaviyo returns the existing profile_id in the error.
            try:
                return r.json()["errors"][0]["meta"]["duplicate_profile_id"]
            except Exception:
                return None
        r.raise_for_status()
        return r.json()["data"]["id"]

    def create_event(self, email: str, metric_name: str, when: datetime) -> bool:
        body = {
            "data": {
                "type": "event",
                "attributes": {
                    "properties": {"merchant_id": self.merchant_id, "seeded": True},
                    "metric": {
                        "data": {
                            "type": "metric",
                            "attributes": {"name": metric_name},
                        }
                    },
                    "profile": {
                        "data": {"type": "profile", "attributes": {"email": email}}
                    },
                    "time": when.isoformat(),
                },
            }
        }
        r = self.client.post("https://a.klaviyo.com/api/events", json=body)
        return r.status_code < 400

    def seed_from_shopify(
        self,
        events_per_customer: int = 6,
        extra_prospects: int = 12,
    ) -> dict[str, int]:
        """Seed Klaviyo profiles + events.

        Two cohorts:
        - Customers — Klaviyo profiles for each Shopify customer (email match).
          Each gets `events_per_customer` engagement events.
        - Prospects — `extra_prospects` Klaviyo-only profiles (NO Shopify match)
          with varied engagement intensity (light/medium/high). These give
          find_engaged_non_buyers something real to surface.
        """
        customers = self._shopify_customers()
        if not customers:
            raise RuntimeError(
                "No Shopify customers with email in canonical store. "
                "Run `d2c project default --source shopify` first."
            )

        results: dict[str, int] = {
            "profiles": 0,
            "prospects": 0,
            "events": 0,
            "errors": 0,
        }
        now = datetime.now(timezone.utc)

        # Buyer cohort — matches Shopify customers by email.
        for c in customers:
            email = c["email"]
            try:
                self.upsert_profile(email)
                results["profiles"] += 1
            except httpx.HTTPStatusError as e:
                results["errors"] += 1
                print(
                    f"  profile {email}: {e.response.status_code} "
                    f"{e.response.text[:200]}"
                )
                continue

            for _ in range(events_per_customer):
                days_ago = random.randint(0, 30)
                when = now - timedelta(
                    days=days_ago, hours=random.randint(0, 23)
                )
                metric = random.choices(
                    EMAIL_METRICS, weights=EMAIL_WEIGHTS, k=1
                )[0]
                if self.create_event(email, metric, when):
                    results["events"] += 1
                else:
                    results["errors"] += 1
                time.sleep(0.05)

        # Prospect cohort — engaged-but-not-buying. Varied intensity so the
        # engaged_non_buyers tool has a meaningful distribution to surface.
        for i in range(extra_prospects):
            email = f"prospect-{i + 1:02d}@seeded.local"
            try:
                self.upsert_profile(email)
                results["prospects"] += 1
            except httpx.HTTPStatusError as e:
                results["errors"] += 1
                print(
                    f"  prospect {email}: {e.response.status_code} "
                    f"{e.response.text[:200]}"
                )
                continue

            intensity = random.choices(
                ["light", "medium", "high"], weights=[40, 40, 20], k=1
            )[0]
            num_events = {"light": 2, "medium": 5, "high": 9}[intensity]
            # Prospects skew toward opens/clicks (they wouldn't appear as warm
            # otherwise) — adjust weights vs buyer cohort.
            prospect_weights = [25, 50, 25]

            for _ in range(num_events):
                days_ago = random.randint(0, 30)
                when = now - timedelta(
                    days=days_ago, hours=random.randint(0, 23)
                )
                metric = random.choices(
                    EMAIL_METRICS, weights=prospect_weights, k=1
                )[0]
                if self.create_event(email, metric, when):
                    results["events"] += 1
                else:
                    results["errors"] += 1
                time.sleep(0.05)
        return results

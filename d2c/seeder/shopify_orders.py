"""Seed realistic orders into a Shopify dev store.

Creates draft orders with varied line items + discount patterns, then marks
each as paid (payment_pending=false bypasses real payment flow). Used to give
the watcher loop something to chew on — especially the heavy-discount tail
that the agent should flag.

Dev/free stores rate-limit draft order creation to 5/min. Built-in sliding
window paces requests; expect roughly (count - 5) * 12 seconds for `count`
orders past the initial burst.
"""

import random
import time
from collections import deque
from typing import Any

import httpx

from d2c.config import MerchantConfig

# Discount distribution: (percentage, weight). 40%+ orders are the "leakage"
# tail the watcher loop should surface.
DISCOUNT_DISTRIBUTION: list[tuple[float, int]] = [
    (0.0, 50),
    (10.0, 25),
    (20.0, 15),
    (30.0, 5),
    (50.0, 5),
]

LINE_COUNT_DISTRIBUTION: list[tuple[int, int]] = [
    (1, 55),
    (2, 30),
    (3, 10),
    (4, 5),
]

# Shopify dev/free stores cap draft order creation. Hardcoded — quirk of
# the dev tier, not a config dimension.
DEV_DRAFT_RATE_LIMIT_COUNT = 5
DEV_DRAFT_RATE_WINDOW_SEC = 65  # 60s window + buffer


class ShopifyOrderSeeder:
    def __init__(self, merchant_config: MerchantConfig):
        cfg = merchant_config.connectors["shopify"]
        self.shop_domain = cfg["shop_domain"]
        self.api_version = cfg.get("api_version", "2024-10")
        self.token = merchant_config.secret("SHOPIFY_ADMIN_API_TOKEN")
        self.base_url = f"https://{self.shop_domain}/admin/api/{self.api_version}"
        self.client = httpx.Client(
            headers={
                "X-Shopify-Access-Token": self.token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._draft_timestamps: deque[float] = deque(maxlen=DEV_DRAFT_RATE_LIMIT_COUNT)

    def close(self) -> None:
        self.client.close()

    def fetch_variants(self) -> list[dict[str, Any]]:
        variants: list[dict[str, Any]] = []
        url: str | None = f"{self.base_url}/products.json?limit=250"
        while url:
            response = self.client.get(url)
            response.raise_for_status()
            data = response.json()
            for product in data.get("products", []):
                for variant in product.get("variants", []):
                    variants.append(
                        {"id": variant["id"], "price": float(variant["price"])}
                    )
            link = response.headers.get("Link", "")
            url = None
            if 'rel="next"' in link:
                for part in link.split(","):
                    if 'rel="next"' in part:
                        url = part.split(";")[0].strip()[1:-1]
                        break
        return variants

    def fetch_customers(self) -> list[dict[str, Any]]:
        response = self.client.get(f"{self.base_url}/customers.json?limit=250")
        response.raise_for_status()
        return response.json().get("customers", [])

    @staticmethod
    def _sample(distribution: list[tuple[Any, int]]) -> Any:
        choices, weights = zip(*distribution)
        return random.choices(choices, weights=list(weights), k=1)[0]

    def _wait_for_draft_window(self) -> None:
        if len(self._draft_timestamps) < DEV_DRAFT_RATE_LIMIT_COUNT:
            return
        oldest = self._draft_timestamps[0]
        elapsed = time.monotonic() - oldest
        if elapsed < DEV_DRAFT_RATE_WINDOW_SEC:
            wait = DEV_DRAFT_RATE_WINDOW_SEC - elapsed
            print(f"  rate-window full; waiting {wait:.0f}s...")
            time.sleep(wait)

    def _request_with_retry(
        self, method: str, url: str, **kwargs: Any
    ) -> dict[str, Any]:
        for attempt in range(2):
            r = self.client.request(method, url, **kwargs)
            if r.status_code == 429 and attempt == 0:
                print("  unexpected 429; sleeping 65s and retrying...")
                time.sleep(65)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("Unreachable")

    def create_paid_order(
        self,
        variants: list[dict[str, Any]],
        customers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._wait_for_draft_window()

        customer = random.choice(customers)
        num_lines = self._sample(LINE_COUNT_DISTRIBUTION)
        picked = random.sample(variants, min(num_lines, len(variants)))
        line_items = [
            {"variant_id": v["id"], "quantity": random.randint(1, 3)} for v in picked
        ]
        discount_pct = self._sample(DISCOUNT_DISTRIBUTION)

        draft_body: dict[str, Any] = {
            "draft_order": {
                "line_items": line_items,
                "customer": {"id": customer["id"]},
                "tags": "seeded",
            }
        }
        if discount_pct > 0:
            draft_body["draft_order"]["applied_discount"] = {
                "value_type": "percentage",
                "value": str(discount_pct),
                "title": f"Discount {discount_pct:.0f}%",
            }

        draft_resp = self._request_with_retry(
            "POST", f"{self.base_url}/draft_orders.json", json=draft_body
        )
        draft = draft_resp["draft_order"]
        self._draft_timestamps.append(time.monotonic())

        complete_resp = self._request_with_retry(
            "PUT",
            f"{self.base_url}/draft_orders/{draft['id']}/complete.json",
            params={"payment_pending": "false"},
        )
        return complete_resp["draft_order"]

    def seed(self, count: int) -> dict[str, int]:
        variants = self.fetch_variants()
        customers = self.fetch_customers()
        if not variants or not customers:
            raise RuntimeError(
                f"Dev store missing data: variants={len(variants)}, customers={len(customers)}"
            )
        print(f"  using {len(variants)} variants, {len(customers)} customers")

        results: dict[str, int] = {"created": 0, "errors": 0}
        for i in range(count):
            try:
                self.create_paid_order(variants, customers)
                results["created"] += 1
                if (i + 1) % 5 == 0:
                    print(f"  {i + 1}/{count} orders created so far")
            except httpx.HTTPStatusError as e:
                results["errors"] += 1
                print(
                    f"  order {i + 1}/{count} failed: "
                    f"{e.response.status_code} {e.response.text[:200]}"
                )
        return results

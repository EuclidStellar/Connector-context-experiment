from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx

from d2c.connectors.base import Connector
from d2c.envelope import Envelope, content_envelope_id


def normalize_shop_domain(domain: str) -> str:
    """Strip protocol, whitespace, and trailing slash from a Shopify domain.

    Users sometimes paste `https://my-store.myshopify.com` or
    `my-store.myshopify.com/` into the init prompt; both normalize to
    `my-store.myshopify.com`. Saves a DNS-resolution failure later.
    """
    domain = domain.strip()
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
            break
    return domain.rstrip("/")


class ShopifyConnector(Connector):
    source = "shopify"
    connector_version = "0.0.1"

    OBJECT_TYPES: tuple[str, ...] = ("orders", "products", "customers")

    def __init__(self, merchant_id: str, config: dict[str, Any], secrets: dict[str, str]):
        super().__init__(merchant_id, config, secrets)
        self.shop_domain = normalize_shop_domain(config["shop_domain"])
        self.api_version = config.get("api_version", "2024-10")
        self.token = secrets["SHOPIFY_ADMIN_API_TOKEN"]
        self.base_url = f"https://{self.shop_domain}/admin/api/{self.api_version}"
        self._client = httpx.Client(
            headers={
                "X-Shopify-Access-Token": self.token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def poll(self, since: datetime | None) -> Iterator[Envelope]:
        for object_type in self.OBJECT_TYPES:
            yield from self._poll_object_type(object_type, since)

    def _poll_object_type(
        self, object_type: str, since: datetime | None
    ) -> Iterator[Envelope]:
        url: str | None = f"{self.base_url}/{object_type}.json"
        params: dict[str, str] = {"limit": "250"}
        if object_type == "orders":
            params["status"] = "any"
        if since is not None:
            params["updated_at_min"] = since.isoformat()

        while url:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            for record in data.get(object_type, []):
                yield self._to_envelope(object_type, record)

            url, params = self._next_page(response)

    def _to_envelope(self, object_type: str, record: dict[str, Any]) -> Envelope:
        singular = object_type.rstrip("s")
        source_id = str(record["id"])
        updated_at_str = record.get("updated_at")
        source_updated_at = (
            datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            if updated_at_str
            else None
        )
        envelope_id = content_envelope_id(
            self.merchant_id, self.source, singular, source_id, record
        )
        return Envelope(
            envelope_id=envelope_id,
            merchant_id=self.merchant_id,
            source=self.source,
            source_version=self.api_version,
            connector_version=self.connector_version,
            source_object_type=singular,
            source_object_id=source_id,
            source_updated_at=source_updated_at,
            payload=record,
        )

    @staticmethod
    def _next_page(response: httpx.Response) -> tuple[str | None, dict[str, str]]:
        # Shopify pagination: Link header with rel="next" and rel="previous"
        link_header = response.headers.get("Link", "")
        if 'rel="next"' not in link_header:
            return None, {}
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip()[1:-1]
                # Next-page URL already has the cursor query param; no extra params.
                return url, {}
        return None, {}

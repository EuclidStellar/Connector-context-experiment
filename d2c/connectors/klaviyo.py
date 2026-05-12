from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx

from d2c.connectors.base import Connector
from d2c.envelope import Envelope, content_envelope_id


class KlaviyoConnector(Connector):
    source = "klaviyo"
    connector_version = "0.0.1"

    OBJECT_TYPES: tuple[str, ...] = ("profiles", "metrics", "events")

    # Klaviyo's filter syntax requires the right timestamp field per resource.
    FILTER_FIELDS: dict[str, str | None] = {
        "profiles": "updated",
        "events": "datetime",
        "metrics": None,  # metrics rarely change; no filter needed
    }

    def __init__(self, merchant_id: str, config: dict[str, Any], secrets: dict[str, str]):
        super().__init__(merchant_id, config, secrets)
        self.api_key = secrets["KLAVIYO_PRIVATE_API_KEY"]
        self.api_revision = config.get("api_revision", "2024-10-15")
        self.base_url = "https://a.klaviyo.com/api"
        # Klaviyo's events endpoint is occasionally slow when the index is hot
        # from recent writes. 60s + per-call retry-on-timeout is enough headroom.
        self._client = httpx.Client(
            headers={
                "Authorization": f"Klaviyo-API-Key {self.api_key}",
                "revision": self.api_revision,
                "accept": "application/json",
                "content-type": "application/json",
            },
            timeout=60.0,
        )

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def poll(self, since: datetime | None) -> Iterator[Envelope]:
        for object_type in self.OBJECT_TYPES:
            yield from self._poll_object_type(object_type, since)

    # Smaller pages on the heavy endpoint = friendlier to flaky networks
    # (corporate VPNs, intermittent DNS) and faster fail-and-retry on issues.
    PAGE_SIZE_OVERRIDES: dict[str, int] = {"events": 20, "profiles": 50}

    def _poll_object_type(
        self, object_type: str, since: datetime | None
    ) -> Iterator[Envelope]:
        url: str | None = f"{self.base_url}/{object_type}"
        params: dict[str, Any] = {}
        page_size = self.PAGE_SIZE_OVERRIDES.get(object_type)
        if page_size:
            params["page[size]"] = page_size
        filter_field = self.FILTER_FIELDS.get(object_type)
        if since is not None and filter_field:
            iso = since.isoformat().replace("+00:00", "Z")
            params["filter"] = f"greater-than({filter_field},{iso})"

        while url:
            response = self._get_with_retry(url, params)
            data = response.json()

            for item in data.get("data", []):
                yield self._to_envelope(object_type, item)

            next_link = (data.get("links") or {}).get("next")
            url = next_link
            params = {}  # next-page link already includes all params

    def _get_with_retry(
        self, url: str, params: dict[str, Any], max_retries: int = 3
    ) -> httpx.Response:
        """GET with retry on transient network errors. Catches the wider
        httpx.TransportError so flaky networks (corporate VPNs, intermittent
        DNS) don't kill the sync — exponential backoff between attempts."""
        import time
        for attempt in range(max_retries + 1):
            try:
                r = self._client.get(url, params=params)
                r.raise_for_status()
                return r
            except (httpx.TransportError, httpx.ReadTimeout, httpx.ConnectTimeout):
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise

    def _to_envelope(self, object_type: str, record: dict[str, Any]) -> Envelope:
        singular = object_type.rstrip("s")
        source_id = record["id"]
        attrs = record.get("attributes", {}) or {}
        ts = attrs.get("updated") or attrs.get("datetime") or attrs.get("created")
        source_updated_at = None
        if isinstance(ts, str):
            try:
                source_updated_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                pass
        envelope_id = content_envelope_id(
            self.merchant_id, self.source, singular, source_id, record
        )
        return Envelope(
            envelope_id=envelope_id,
            merchant_id=self.merchant_id,
            source=self.source,
            source_version=self.api_revision,
            connector_version=self.connector_version,
            source_object_type=singular,
            source_object_id=source_id,
            source_updated_at=source_updated_at,
            payload=record,
        )

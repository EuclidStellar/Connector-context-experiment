from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import httpx

from d2c.connectors.base import Connector
from d2c.envelope import Envelope, content_envelope_id


class RazorpayConnector(Connector):
    source = "razorpay"
    connector_version = "0.0.1"

    # v0: orders only. Payments/refunds added when there's enough data in
    # test mode to justify them — direct payment creation requires checkout
    # flow that the dev path doesn't easily exercise.
    OBJECT_TYPES: tuple[str, ...] = ("orders",)

    def __init__(self, merchant_id: str, config: dict[str, Any], secrets: dict[str, str]):
        super().__init__(merchant_id, config, secrets)
        self.key_id = secrets["RAZORPAY_KEY_ID"]
        self.key_secret = secrets["RAZORPAY_KEY_SECRET"]
        self.base_url = "https://api.razorpay.com/v1"
        self._client = httpx.Client(
            auth=(self.key_id, self.key_secret),
            headers={"Content-Type": "application/json"},
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

    # Razorpay's /orders listing index is eventually-consistent — newly created
    # orders can take a few minutes to appear. Always rewind the cursor by this
    # much to absorb the lag; INSERT OR IGNORE upstream handles dedup.
    FRESHNESS_BUFFER_SECONDS = 600  # 10 minutes

    def _poll_object_type(
        self, object_type: str, since: datetime | None
    ) -> Iterator[Envelope]:
        url = f"{self.base_url}/{object_type}"
        params: dict[str, Any] = {"count": 100}
        if since is not None:
            buffered = since.timestamp() - self.FRESHNESS_BUFFER_SECONDS
            params["from"] = int(buffered)

        skip = 0
        while True:
            params["skip"] = skip
            response = self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            items = data.get("items", []) or []
            for item in items:
                yield self._to_envelope(object_type, item)
            if len(items) < params["count"]:
                break
            skip += len(items)

    def _to_envelope(self, object_type: str, record: dict[str, Any]) -> Envelope:
        singular = object_type.rstrip("s")
        source_id = str(record["id"])
        created_ts = record.get("created_at")  # Razorpay returns Unix seconds (int)
        source_updated_at = (
            datetime.fromtimestamp(int(created_ts), tz=timezone.utc)
            if created_ts is not None
            else None
        )
        envelope_id = content_envelope_id(
            self.merchant_id, self.source, singular, source_id, record
        )
        return Envelope(
            envelope_id=envelope_id,
            merchant_id=self.merchant_id,
            source=self.source,
            source_version="v1",
            connector_version=self.connector_version,
            source_object_type=singular,
            source_object_id=source_id,
            source_updated_at=source_updated_at,
            payload=record,
        )

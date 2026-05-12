from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from d2c.envelope import Envelope


class Connector(ABC):
    """Adapter from a foreign SaaS API to envelope-shaped records.

    Source-shape preservation: lands envelopes, does not interpret. Each
    connector exposes poll(since) which yields envelopes for records updated
    since the cursor. Caller advances cursors after envelopes are landed.
    """

    source: str
    connector_version: str = "0.0.1"

    def __init__(self, merchant_id: str, config: dict[str, Any], secrets: dict[str, str]):
        self.merchant_id = merchant_id
        self.config = config
        self.secrets = secrets

    @abstractmethod
    def poll(self, since: datetime | None) -> Iterator[Envelope]:
        """Yield envelopes for records updated since `since`.

        `since=None` means full backfill — use sparingly; sources are paginated.
        """
        raise NotImplementedError

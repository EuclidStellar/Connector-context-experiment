# Connector layer in depth

One interface, three real implementations, swappable.

## The contract

Every connector inherits from a single abstract base class. That's the
entire surface area the rest of the system depends on.

```python
# d2c/connectors/base.py
class Connector(ABC):
    source: str
    connector_version: str

    @abstractmethod
    def poll(self, since: datetime | None) -> Iterator[Envelope]:
        """Yield envelopes for records updated since `since`.
        `since=None` means full backfill — use sparingly; sources are paginated."""
```

That's it. Two attributes, one method.

A connector knows:
- How to authenticate against its source
- Which object types to pull and in what order
- How that source paginates
- How to mint an envelope from a raw record

A connector does *not* know:
- About the canonical model
- About projections
- About merchants other than the one passed in
- About the agent layer

## Three implementations, same shape

```
                   poll(since: datetime|None) → Iterator[Envelope]
                                  │
            ┌─────────────────────┼─────────────────────┐
            ▼                     ▼                     ▼
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│  ShopifyConnector   │ │  RazorpayConnector  │ │  KlaviyoConnector   │
│                     │ │                     │ │                     │
│  Auth: X-Shopify-   │ │  Auth: HTTP Basic   │ │  Auth: Bearer +     │
│        Access-Token │ │        (key:secret) │ │        revision     │
│                     │ │                     │ │                     │
│  Pagination:        │ │  Pagination:        │ │  Pagination:        │
│  Link header        │ │  skip + count       │ │  JSON:API links.next│
│                     │ │                     │ │                     │
│  Cursor param:      │ │  Cursor param:      │ │  Cursor (filter):   │
│  updated_at_min     │ │  from (Unix ts)     │ │  greater-than(...)  │
│                     │ │                     │ │                     │
│  Object types:      │ │  Object types:      │ │  Object types:      │
│  orders, products,  │ │  orders             │ │  profiles, metrics, │
│  customers          │ │                     │ │  events             │
│                     │ │                     │ │                     │
│  Quirks:            │ │  Quirks:            │ │  Quirks:            │
│  - Protected        │ │  - 10-min freshness │ │  - Smaller page     │
│    customer data    │ │    buffer for index │ │    size on events   │
│    scrubs PII       │ │    lag              │ │    (slow endpoint)  │
│                     │ │  - Draft order rate │ │  - System metrics   │
│                     │ │    limit (5/min)    │ │    can't be POSTed  │
│                     │ │    on dev stores    │ │    via /api/events  │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
            │                     │                     │
            └─────────────────────┼─────────────────────┘
                                  ▼
                       Envelope (uniform shape)
```

Each cell in that diagram is a hard-won fact. The plumbing looks the same
(httpx client, paginate-until-empty, retry-on-transient), but the *quirks*
are real and each one cost a debugging session to discover. The connector
code is where the real-world friction lives; everything above it can be
oblivious.

## Sync orchestration

`d2c/sync.py` is a single function plus a registry:

```python
CONNECTOR_REGISTRY: dict[str, type[Connector]] = {
    "shopify":  ShopifyConnector,
    "razorpay": RazorpayConnector,
    "klaviyo":  KlaviyoConnector,
}

def sync_one(merchant_config, source, raw_lake_dir, conn) -> dict:
    connector = CONNECTOR_REGISTRY[source](
        merchant_id=merchant_config.merchant_id,
        config=merchant_config.connectors[source],
        secrets=merchant_config.secrets,
    )
    since = _read_cursor(conn, merchant_id, source)    # conservative-min across object_types
    for envelope in connector.poll(since):
        is_new = raw_lake.land(conn, raw_lake_dir, envelope)
        # ... track counts, max source_updated_at per object_type
    _write_cursor(conn, ..., max_updated, started_at)
```

Adding a 4th source is a one-line change to the registry, plus the
connector implementation. The rest of the codebase doesn't move.

## The two retries that matter

**Conservative cursor:** when multiple object types share a (merchant, source),
we use the *minimum* per-object cursor to choose `since`. That over-fetches
unchanged records, but content-addressed envelope IDs make over-fetch a
no-op. The alternative — per-type cursors — would risk gaps if one type
fails mid-sync.

**Freshness buffer (Razorpay):** the `/v1/orders` listing index is
eventually consistent. Just-created orders take a few minutes to appear.
The connector rewinds the cursor by 10 minutes on every poll:

```python
# d2c/connectors/razorpay.py
FRESHNESS_BUFFER_SECONDS = 600

if since is not None:
    buffered = since.timestamp() - self.FRESHNESS_BUFFER_SECONDS
    params["from"] = int(buffered)
```

INSERT OR IGNORE makes the buffer overhead invisible — we re-fetch the
overlap window, it gets dedup'd, and we never miss a late-indexed record.

## The retry pattern (Klaviyo's was painful to discover)

Klaviyo's `/api/events` endpoint occasionally drops a long-running query
mid-flight, especially when the index is hot from recent writes. The
connector wraps each GET in a typed retry:

```python
# d2c/connectors/klaviyo.py
def _get_with_retry(self, url, params, max_retries=3):
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
```

Plus smaller per-resource page sizes on the heaviest endpoint:

```python
PAGE_SIZE_OVERRIDES: dict[str, int] = {"events": 20, "profiles": 50}
```

This pattern needs to be lifted into the connector base class — it lives
in Klaviyo right now because that's where we hit the failure. **It is
honestly missing from the Shopify and Razorpay pollers.** See
[failure modes](./scale-and-failure-modes.md#what-breaks).

## Seeders are a separate concern

For each connector there's also a seeder that *writes* to the source SaaS:

- `d2c/seeder/shopify_orders.py` — creates draft orders, completes them
  as paid. Has its own sliding-window rate limiter for the dev-store
  5-orders/minute cap.
- `d2c/seeder/razorpay_orders.py` — creates Razorpay orders linked to
  Shopify orders via `notes.shopify_order_number`. Injects a ~15% gap
  rate (lower amount than Shopify net) so the reconciliation demo has
  signal.
- `d2c/seeder/klaviyo_events.py` — creates Klaviyo profiles (for buyers
  + 12 prospects) and Demo Email engagement events.

Seeders are *not* connectors. They exist purely to make the system
demonstrable when the source SaaS account is empty. Production deployments
don't run seeders.

## Adding a 4th connector

The recipe, in order:

1. `d2c/connectors/<name>.py` — implement `Connector` ABC.
2. Add to `CONNECTOR_REGISTRY` in `d2c/sync.py`.
3. Add to the click `--source` choices in `d2c/cli/main.py`.
4. `d2c/projections/<name>.py` — implement the source-specific projection.
5. Add to the `project` command dispatch in `d2c/cli/main.py`.
6. (Optional) `d2c/seeder/<name>.py` — if the source needs demo data.

The first connector took ~half a day to write. The third (Klaviyo) took
two hours including the JSON:API quirks. A fourth, with the patterns
established, should be a day of focused work.

## What's missing in the connector layer

Honest list — see [scale and failure modes](./scale-and-failure-modes.md)
for the full version:

- **Retry coverage is uneven.** Klaviyo retries on transport errors.
  Shopify and Razorpay don't. Should be lifted into the base class.
- **No async.** Each sync is sequential httpx. At 10K merchants × multiple
  sources, this becomes the bottleneck.
- **No schema drift detection.** If Shopify renames a field, projections
  break silently. A connector should ship a schema fingerprint and warn
  on mismatch.
- **No OAuth onboarding.** v0 uses static admin tokens. Real multi-tenant
  needs an OAuth install flow per source.
- **No webhook receiver.** v0 polls. Webhooks would cut freshness lag
  but require a tunnel (or cloud receiver) — out of scope for the local
  dev environment we built against.

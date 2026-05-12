# Connector layer

## What this enables

- **Adding a 4th source is a day of work.** One ABC, one registry entry,
  one projection. No other code moves.
- **Source quirks stay contained.** Klaviyo's eventual consistency,
  Razorpay's index lag, Shopify's protected-PII scrubbing — each is a
  detail of its own connector, invisible to everything above.
- **Re-sync is safe.** Content-addressed envelopes + idempotent landing
  mean nothing breaks if you run `d2c sync` twice in a row.

## The whole contract

```python
class Connector(ABC):
    source: str
    connector_version: str

    @abstractmethod
    def poll(self, since: datetime | None) -> Iterator[Envelope]:
        ...
```

That's it. Two attributes, one method. A connector owns auth, pagination,
rate-limiting, and quirk handling for its source. It knows nothing about
the canonical model or the agent.

## Three implementations, same shape

| | Shopify | Razorpay | Klaviyo |
|---|---|---|---|
| Auth | `X-Shopify-Access-Token` header | HTTP Basic (key:secret) | `Klaviyo-API-Key` bearer + revision header |
| Pagination | Link header | `skip` + `count` | JSON:API `links.next` |
| Cursor | `updated_at_min` | `from` (Unix ts) | filter `greater-than(<field>, ...)` |
| Object types | orders, products, customers | orders | profiles, metrics, events |
| Quirk that bit us | Protected customer data scrubs PII unless app is approved | `/orders` index is eventually consistent | System metrics ("Opened Email") can't be POSTed; events endpoint is slow |
| Defense | Synthesize stable email in projection | 10-min freshness buffer on the cursor | Retry on transport errors + smaller page size on events |

## Sync orchestration in one function

```python
# d2c/sync.py
CONNECTOR_REGISTRY = {
    "shopify":  ShopifyConnector,
    "razorpay": RazorpayConnector,
    "klaviyo":  KlaviyoConnector,
}

def sync_one(merchant_config, source, raw_lake_dir, conn):
    connector = CONNECTOR_REGISTRY[source](...)
    since = _read_cursor(conn, merchant_id, source)
    for envelope in connector.poll(since):
        is_new = raw_lake.land(conn, raw_lake_dir, envelope)
    _write_cursor(...)
```

Add a 4th source: one line in the registry, the connector class, a
projection module, one click choice. Done.

## Two patterns worth knowing

**Freshness buffer (Razorpay).** The `/orders` listing index lags creates
by a few minutes. The connector rewinds the cursor by 10 minutes on every
poll. INSERT OR IGNORE makes the overlap free; we never miss a
late-indexed record.

**Typed retry (Klaviyo).** The `/events` endpoint occasionally drops
mid-flight. The connector retries on `httpx.TransportError`,
`ReadTimeout`, `ConnectTimeout` with exponential backoff. Worth lifting
to the base class — currently only Klaviyo has it.

## Seeders (separate concern)

Each connector has a sibling seeder that *writes* to the source SaaS to
make the demo non-empty:

- `shopify_orders.py` — draft orders → marked paid. Sliding-window rate
  limiter for the dev-store 5-orders/min cap.
- `razorpay_orders.py` — one Razorpay order per Shopify order, linked
  via `notes.shopify_order_number`. ~15% injected with a synthetic gap.
- `klaviyo_events.py` — profiles + custom-named email events for buyers
  and 12 engaged prospects.

Seeders are not connectors. Production deployments don't run them.

## What's missing

- **Retry coverage is uneven.** Klaviyo has it; Shopify and Razorpay
  pollers don't. Should be in the base class.
- **No async.** Sequential httpx works at 1 merchant; becomes the
  bottleneck at scale.
- **No schema drift detection.** A renamed Shopify field silently
  breaks downstream until you notice.
- **No OAuth onboarding flow.** v0 uses admin tokens. Real multi-tenant
  onboarding needs OAuth per source.

See [scale-and-failure-modes.md](./scale-and-failure-modes.md).

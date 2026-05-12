# Data layer in depth

The data plane is the substrate everything else stands on. Its job is to
turn whatever the source SaaS returns into something the agent can reason
over — without losing information, without re-fetching, with provenance
on every claim.

## Five stages, end to end

```
[Source API]
     │
     ▼  poll(since)
[Envelope]        ◄── content-addressed UUID; payload preserved verbatim
     │
     ▼  raw_lake.land()  (idempotent: INSERT OR IGNORE)
[Raw Lake]        ◄── JSONL on disk (partitioned by merchant/source/date)
     │                + SQLite envelopes table (the index)
     ▼
[Projections]     ◄── pure functions, one per (source, object_type)
     │                versioned; ON CONFLICT-safe; preserve cross-source columns
     ▼
[Canonical]       ◄── customers, products, orders, order_lines,
     │                shipments, messages, events
     ▼
[Identity res.]   ◄── matches the same person across sources
                      (v0: naive email match; production: confidence-scored)
```

Each stage is physically separate. You can blow away canonical, keep
envelopes, re-project. You can change projection logic and re-run against
the same lake without touching the source APIs again.

## Envelope contract

Every connector produces envelopes. Same shape across sources.

```python
# d2c/envelope.py
class Envelope(BaseModel):
    envelope_id: UUID                  # content-addressed
    merchant_id: str
    source: str                        # "shopify" | "razorpay" | "klaviyo"
    source_version: str                # API version when fetched
    connector_version: str             # version of the connector code
    source_object_type: str            # "order", "profile", "payment"
    source_object_id: str              # the source's primary identifier
    source_event_type: str | None
    fetched_at: datetime               # UTC
    source_updated_at: datetime | None # source's own updated_at if present
    payload: dict[str, Any]            # ORIGINAL response payload, verbatim
```

The `envelope_id` is computed via:

```python
uuid5(NS, f"{merchant_id}|{source}|{type}|{source_id}|{canonical_payload_json}")
```

Same record content → same UUID. `INSERT OR IGNORE` makes idempotent
landing. Records that genuinely *change* (e.g., order status flips from
pending → paid) get a new UUID because the canonicalized payload differs.
**The lake records one row per real change, not one row per fetch.**

## Two physical surfaces

```
data/
├── default/
│   └── canonical.db              SQLite — envelopes index + canonical entities
│                                  + reflective layer (beliefs/decisions/trust)
└── raw_lake/
    └── default/
        ├── shopify/2026-05-12.jsonl
        ├── razorpay/2026-05-12.jsonl
        └── klaviyo/2026-05-12.jsonl   one JSONL line per envelope
```

- **JSONL on disk** is the replay tape. Append-only, partitioned by
  `<merchant>/<source>/<YYYY-MM-DD>`. Survives any DB rebuild.
- **SQLite `envelopes` table** is the index. Fast lookup, dedup, partitioned
  by `merchant_id` in column.

`raw_lake.land()` writes both, idempotently:

```python
# d2c/storage/raw_lake.py
def land(conn, raw_lake_dir, envelope) -> bool:
    cur = conn.execute("INSERT OR IGNORE INTO envelopes ...")
    if cur.rowcount == 0:
        return False    # duplicate; JSONL already has this line; no-op
    # NEW envelope — also append to JSONL
    ...
```

Crash-consistency: DB insert happens *before* JSONL append + commit. If
the JSONL append fails, the transaction rolls back; DB and disk stay in
sync.

## Canonical model

Six entity types plus one universal fallback:

| Entity      | What it is                                  | Sources today                        |
| ----------- | ------------------------------------------- | ------------------------------------ |
| Customer    | A person with any relationship to merchant  | Shopify, Klaviyo                     |
| Product     | A SKU                                       | Shopify                              |
| Order       | A commercial transaction                    | Shopify (Razorpay updates `settled`) |
| OrderLine   | One line on an order                        | Shopify                              |
| Shipment    | Physical movement                           | (none in v0)                         |
| Message     | Communication to/from a customer            | Klaviyo                              |
| **Event**   | Universal fallback — any timestamped fact   | All                                  |

The schema is intentionally small. The architecture resists adding entity
types until forced — the universal `events` table absorbs the long tail.

## Provenance is structural

Every canonical row carries two fields that make every claim recoverable:

- `derived_from_envelope_id` — points to the source envelope that produced it
- `projection_version` — which version of the projection algorithm wrote it

```sql
-- schema/canonical.sql
CREATE TABLE orders (
    canonical_id              TEXT NOT NULL,
    merchant_id               TEXT NOT NULL,
    derived_from_envelope_id  TEXT NOT NULL,    -- provenance
    projection_version        TEXT NOT NULL,    -- lazy re-projection
    ...
    PRIMARY KEY (canonical_id, projection_version),
    FOREIGN KEY (derived_from_envelope_id) REFERENCES envelopes(envelope_id)
);
```

When the agent cites a number, the citation IS the `derived_from_envelope_id`.
The [citation validator](./04-agent-layer.md#citation-contract) verifies that
envelope row actually exists before any output reaches the user.

## ON CONFLICT-safe projections (cross-source updates)

Razorpay's projection updates `orders.settled_revenue` on rows that
Shopify created. If the Shopify projection used `INSERT OR REPLACE`,
re-running it would blow away the Razorpay-written column. So the Shopify
projection uses explicit `ON CONFLICT DO UPDATE`, listing only the
Shopify-owned columns:

```python
# d2c/projections/shopify.py
INSERT INTO orders (...) VALUES (...)
ON CONFLICT(canonical_id, projection_version) DO UPDATE SET
    derived_from_envelope_id = excluded.derived_from_envelope_id,
    gross_revenue            = excluded.gross_revenue,
    total_discount           = excluded.total_discount,
    ...
    -- settled_revenue intentionally NOT updated (Razorpay owns it)
```

This is the kind of detail that turns *"yeah, the architecture supports
cross-source updates"* into actually-working code.

## Lazy re-projection

`projection_version` is in the primary key, so multiple versions of the
same canonical row can coexist. When we ship `shopify-v2`:

- old `shopify-v1` rows stay
- new `shopify-v2` rows are written
- queries opt into a version explicitly
- we re-project lazily, not via a big-bang migration

For v0 only the `v1` versions exist. The pattern is provisioned, not yet
exercised.

## Idempotency end-to-end

Re-running every step is safe by construction:

| Step           | Idempotency mechanism                                     |
| -------------- | --------------------------------------------------------- |
| Source poll    | Cursor-based `updated_at_min`; conservative-min across types |
| Envelope land  | Content-addressed `envelope_id` + `INSERT OR IGNORE`         |
| Canonical proj | `INSERT … ON CONFLICT DO UPDATE` on the projection-owned columns |
| Decision write | Append-only `decisions` table; one row per founder action  |

Verified end-to-end: a fresh reset followed by two consecutive syncs
produces unique 1:1 envelope rows on the first run and `0 new, N skipped`
on the second.

## Identity resolution (v0 stopgap vs production)

v0 does a naive email-match inside the Klaviyo projection:

- Klaviyo profile email matches an existing customer → add a `klaviyo` alias.
- No match → create a new canonical customer from the Klaviyo profile.

This works for the demo but is not real identity resolution. Production
needs:

- **Confidence-scored matching** across multiple identifiers (email,
  phone, hashed_email).
- **Three-band policy**: auto-merge above X, surface for review between
  X and Y, never merge below Y.
- **A separate pass** that runs on its own cadence — not coupled to
  ingestion.

The schema for `identity_merges` exists; the logic doesn't.

## What's wired vs scaffolded

Honest accounting:

| Component                                                | Schema | Code         |
| -------------------------------------------------------- | ------ | ------------ |
| Envelopes                                                | ✓      | ✓ live       |
| Sync cursors                                             | ✓      | ✓ live       |
| Customer / Product / Order / OrderLine / Message / Event | ✓      | ✓ live       |
| Shipment projection                                      | ✓      | ✗ (no source ingested) |
| Identity merges                                          | ✓      | ✗ (naive in-line stopgap) |
| Beliefs                                                  | ✓      | ✗ (no code writes)        |
| Decisions                                                | ✓      | ✓ `d2c decide` writes     |
| Trust state                                              | ✓      | partial — read in MCP, no ratcheting |
| Changelog                                                | ✓      | ✗                          |

See [scale and failure modes](./scale-and-failure-modes.md) for what to
build next.

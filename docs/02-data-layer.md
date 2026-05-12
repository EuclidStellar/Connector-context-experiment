# Data layer

## First principle

The data is the truth. Every claim must be reconstructible to the
bytes that produced it. Storage decisions follow from *"what would I
want to ask in six months?"* — not from what's easy to ship today.

## What this enables

- **Bug fixes against historical data.** A projection bug is fixed by
  editing the function and re-running. Zero API calls.
- **New metrics on old data.** Want a metric you didn't think of before?
  Add the column, update the projection, re-run. The bytes are still in
  the lake.
- **Survival of upstream API changes.** Shopify renames a field; the
  envelope still captures it. Update the projection; old data and new
  data converge in the canonical column.
- **"Where did this number come from?"** Every derived row carries
  `derived_from_envelope_id`. The envelope has the verbatim payload and
  `fetched_at`. Provenance is a property of the storage, not a feature.

## Five stages

```
[Source API]
     │  poll(since)
     ▼
[Envelope]           content-addressed UUID; payload preserved verbatim
     │  raw_lake.land()  (INSERT OR IGNORE)
     ▼
[Raw Lake]           JSONL on disk + SQLite envelopes index
     │  projection (pure function, versioned)
     ▼
[Canonical entities] customers, products, orders, order_lines,
     │               shipments, messages, events
     ▼
[Identity resolution] v0 = email match;  production = confidence-scored
```

Each stage is physically separate. Blow away canonical, keep envelopes,
re-project. Change projection logic, re-run against the same lake.

## Envelope — the only shape that crosses the connector boundary

```python
class Envelope(BaseModel):
    envelope_id: UUID                  # content-addressed
    merchant_id: str
    source: str
    source_object_type: str            # "order", "profile", "payment"
    source_object_id: str
    source_event_type: str | None
    fetched_at: datetime
    source_updated_at: datetime | None
    source_version: str
    connector_version: str
    payload: dict[str, Any]            # ORIGINAL response, verbatim
```

`envelope_id = uuid5(NS, "<merchant>|<source>|<type>|<source_id>|<canonical_payload_json>")`.

Same record content → same UUID. Re-sync of unchanged data is a no-op via
`INSERT OR IGNORE`. A record that genuinely changes (order status flips
pending → paid) gets a new UUID because the canonicalized payload differs.
**One row per real change, not one row per fetch.**

## Raw lake — two surfaces

```
data/
├── default/
│   └── canonical.db                    SQLite — envelopes index + canonical
└── raw_lake/default/
    ├── shopify/2026-05-12.jsonl
    ├── razorpay/2026-05-12.jsonl
    └── klaviyo/2026-05-12.jsonl        one JSONL line per envelope
```

`raw_lake.land()` does `INSERT OR IGNORE` first; only on a new row does it
append to the JSONL. DB-side dedup gates the disk write. Crash-safe.

## Canonical model

Six entities + one universal fallback:

| Entity      | What it is                       | Source(s)                                |
|-------------|----------------------------------|------------------------------------------|
| Customer    | Person related to merchant       | Shopify, Klaviyo                         |
| Product     | SKU                              | Shopify                                  |
| Order       | Commercial transaction           | Shopify (Razorpay updates `settled`)     |
| OrderLine   | Line on an order                 | Shopify                                  |
| Shipment    | Physical movement                | (none in v0)                             |
| Message     | Communication to/from customer   | Klaviyo                                  |
| **Event**   | Universal — any timestamped fact | All                                      |

We resist adding entity types. Most analytical questions are Event filters.

## Provenance is in the row, not the comment

Every canonical row carries:
- `derived_from_envelope_id` → points at the source envelope
- `projection_version` → which projection algorithm wrote it

```sql
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

When the agent writes `$1,724.95 [cite:abc-def]`, the cite IS the envelope_id.
The validator confirms the row exists before the user sees the answer.

## Cross-source updates without stomping

Razorpay's projection writes `orders.settled_revenue` on rows that
Shopify created. The Shopify projection uses `ON CONFLICT DO UPDATE` and
explicitly lists only its own columns:

```python
INSERT INTO orders (...) VALUES (...)
ON CONFLICT(canonical_id, projection_version) DO UPDATE SET
    gross_revenue   = excluded.gross_revenue,
    total_discount  = excluded.total_discount,
    ...
    -- settled_revenue intentionally NOT updated (Razorpay owns it)
```

Re-running the Shopify projection doesn't blow away Razorpay-written data.

## v0 today vs next iteration

| Component                                                    | v0 today    | Next iteration                              |
| ------------------------------------------------------------ | ----------- | ------------------------------------------- |
| Envelopes + sync cursors                                     | live        | ✓                                           |
| Customer / Product / Order / OrderLine / Message / Event projections | live | ✓                                           |
| Decisions (write path)                                       | live        | ✓                                           |
| Shipment projection                                          | scaffolded  | wire up when a logistics connector lands    |
| Identity merges                                              | email match | confidence-scored 3-band merge (own pass)   |
| Beliefs / trust ratchet / changelog                          | schema      | emission + ratchet (~150 LOC)               |

Each row in the right column is a focused slice of work on the existing
architecture — no redesign required. See
[scale-and-failure-modes.md](./scale-and-failure-modes.md) for the
production evolution per component.

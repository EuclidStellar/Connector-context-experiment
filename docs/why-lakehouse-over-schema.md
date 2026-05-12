# Why a lakehouse, not just a normalized schema

The naive ingestion design for a system like this is:

```
[Source API]  →  [transform to canonical schema]  →  [discard original]
                                ↓
                       [canonical DB only]
```

Pull the records, immediately map them to your own schema, throw away the
source bytes. It's simpler. It's tempting. And it forecloses an entire
class of future answers.

## The shape we picked instead

```
[Source API]
      ↓
[Envelope]  ◄── source bytes, verbatim, content-addressed
      ↓
[Raw Lake]  ◄── append-only, partitioned, dedup'd
      ↓                                ▲
[Projection]  (pure function)          │ re-run anytime, no API hit
      ↓                                │
[Canonical DB]  ─────────────────────  ┘
```

The envelope is *source-faithful*. Every byte the API returned is preserved
verbatim. The canonical DB is a *derived* view, computed by a pure function
from the lake.

## What this buys you (in concrete scenarios)

### Scenario 1: you fix a bug in the projection

Six weeks in, you notice that `orders.net_revenue` is wrong for orders
with multi-currency line items. The projection logic miscomputes.

**With a normalized schema:** the wrong numbers are in your DB. The
source bytes are gone. To fix, you either (a) re-fetch from Shopify
(rate-limited, slow, may have lost historical records to API retention
windows) or (b) write a hand-coded migration to recompute from what
you have left.

**With this lakehouse shape:** edit the projection function. Run
`d2c project default --source shopify` again. The function reads
envelopes from the lake and rewrites canonical rows. Zero API calls.
Zero data loss. Done in two minutes.

### Scenario 2: you want to add a new metric you didn't think of before

You realize you want to track `time_from_first_order_to_second_order`
per customer. The data is in your orders, but you never computed this
metric.

**With a normalized schema:** the projection happened at ingest time
and dropped fields you didn't need. If you're lucky, the canonical
`orders` table still has enough to derive this. If you weren't lucky
— say, you dropped `customer.created_at` because you didn't need it
— you have to re-fetch.

**With this lakehouse shape:** the envelope payload is verbatim. The
field is in there. Add a column to canonical, write the projection to
populate it, re-run. The lake has everything the source ever told you.

### Scenario 3: Shopify changes their API

Shopify renames `total_discounts` to `discount_amount` in API v2025-01.

**With a normalized schema:** ingestion silently breaks (NULL where there
used to be a number). You only notice when canonical numbers go wrong.
Production data quietly degrades.

**With this lakehouse shape:** the envelope still captures whatever
Shopify returns (it's just a dict). The projection sees `discount_amount`
where it used to see `total_discounts`. You can:
- Update the projection to read both old + new keys (smooth transition).
- Re-project against the lake — old data with old key, new data with
  new key, both end up in the same canonical column.
- Schema drift detection (not yet built, see
  [scale and failure modes](./scale-and-failure-modes.md)) catches it
  proactively.

### Scenario 4: legal asks "where did this number come from?"

Founder hands a board deck with revenue numbers. Investor follow-up:
*"Reconcile this against your Razorpay statements."*

**With a normalized schema:** the canonical `revenue` column. Where did
it come from? A projection that ran six months ago against API data
that's no longer available the same way it was then.

**With this lakehouse shape:** every canonical row carries
`derived_from_envelope_id`. The envelope has `fetched_at`, `source_version`,
and the verbatim payload. You can show, byte-for-byte, what Shopify
returned on the day you computed that number. **Provenance is not a
feature; it's a property of the storage.**

## The pattern is "event sourcing with CQRS"

Worth naming the pattern explicitly, because it has decades of theory
behind it:

```
WRITE MODEL    │   READ MODEL(S)
               │
[envelopes]    │   [canonical entities]
append-only,   │   derived, versioned, re-derivable
immutable,     │
source of      │
truth          │
```

- **Event sourcing**: the lake is the append-only log of source events.
- **CQRS** (Command-Query Responsibility Segregation): write model
  (envelopes) is separate from read model (canonical entities). The
  canonical model can change shape without losing the underlying truth.

We don't make a big deal of it in the code because the pattern is
conventional in data engineering. But the *consequences* — re-projection,
schema evolution, provenance — are all things that fall out of getting
the shape right.

## What it costs

Not free:

1. **Storage roughly 2x** (envelopes + canonical), but JSONL compresses
   well and SQLite envelope rows are small. For the scale we care about,
   trivial.
2. **One extra projection step** before queries return results. But
   projection is fast (pure function over already-local data), and
   re-projection is a feature, not a tax.
3. **Identity resolution gets harder** because customers can land in
   the lake from multiple sources before they're known to be the same
   person. The lake doesn't solve identity resolution; it just doesn't
   force you to solve it at ingest time. See
   [data layer](./02-data-layer.md#identity-resolution-v0-stopgap-vs-production)
   for the deferred-reconciliation pattern.

## Counter-argument we considered

*"Just use Postgres with JSONB columns and you get the same thing."*

Half-true. JSONB columns in Postgres do give you source-faithful storage.
But:

- JSONL on disk is more portable. Replay across systems, copy to S3,
  archive cheaply.
- A two-surface design (disk + DB) means the disk is durable independently
  of DB state. We can blow away the DB and re-index from JSONL.
- JSONB columns optimize for live query, not for the "store now, project
  later" pattern. The pattern works in either, but the lake shape makes
  the intent obvious.

For v0 on a laptop with SQLite, the JSONL + SQLite combination is
unbeatable for inspectability — you can `cat data/raw_lake/.../*.jsonl`
and read everything you've ever ingested. Production at scale would
swap SQLite for Postgres and JSONL for Parquet on object storage; the
*pattern* doesn't change.

## When NOT to do this

If your sources are:
- Stable (no API drift)
- High-cardinality but low-volume per record
- Always available for re-fetch (no retention limit)
- Trivially canonicalizable (no semantic ambiguity)

…then a direct ingest-to-canonical design is fine. You don't need the
lake.

For D2C SaaS sources, *none* of those four properties hold. Shopify
changes APIs. Razorpay's listing index has eventual consistency. Klaviyo's
events index can be slow. Identity resolution across sources is genuinely
hard. Schema-only ingest would have hit at least three of those walls
within the first month of operation.

So we built the lake.

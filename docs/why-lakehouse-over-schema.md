# Why a lakehouse, not just a schema

## What this design buys us

- **Bug in a projection?** Edit the function, re-run. Zero API calls.
- **Want a new metric you didn't think of before?** Add the column,
  update the projection, re-run against the existing lake.
- **Source API changes a field name?** Envelope still captures it.
  Update the projection to handle both old and new keys. Re-project.
- **Legal/finance: "where did this number come from?"** Every row has
  `derived_from_envelope_id`; the envelope has the verbatim payload
  with `fetched_at`. Reconstructible by row.

## The shape

```
[Source API]
      ↓
[Envelope]      ◄── source bytes, verbatim, content-addressed
      ↓
[Raw Lake]      ◄── append-only, partitioned, dedup'd
      ↓                              ▲
[Projection]    (pure function)      │  re-run anytime, no API hit
      ↓                              │
[Canonical DB]  ────────────────────┘
```

Source-faithful storage is the write model. Canonical is a derived read
model, computed by pure functions from the lake. Standard pattern: event
sourcing + CQRS.

## What the alternative costs

A "transform at ingest, throw away source bytes" design is simpler. It
also gives up:

- **Fixing bugs in derived data.** The source bytes are gone. Re-fetch
  if you can (rate limits, retention windows); hand-migrate if you can't.
- **Adding metrics retroactively.** You can only compute over what you
  chose to keep. Anything you discarded at ingest is permanently lost.
- **Surviving schema drift.** If Shopify renames a field, ingestion
  silently breaks. Your canonical numbers degrade quietly.
- **Auditability.** No way to prove what the source returned on a given
  day.

For D2C SaaS sources — where APIs drift, indexes lag, identity is hard,
and semantics are subtle — none of these are theoretical risks. We hit
at least three of them during the build.

## What this design costs

- **Roughly 2× storage.** Envelopes + canonical. JSONL compresses well;
  SQLite envelopes rows are small. At v0 scale, trivial.
- **One extra step per query.** Projection sits between source and read.
  Pure function over local data; fast.
- **Identity resolution is harder.** Customers can land in the lake from
  multiple sources before they're known to be the same person. The
  lake doesn't solve identity resolution — it stops forcing you to
  solve it at ingest time. See
  [data layer](./02-data-layer.md#provenance-is-in-the-row-not-the-comment).

## Why not just JSONB columns in Postgres

JSONB columns give you source-faithful storage too. Difference:

- JSONL on disk is more portable. Copy across systems, archive to
  object storage, inspect with `cat`.
- Two-surface (disk + DB) means disk is durable independently of DB
  state. Blow away the DB, re-index from JSONL.
- JSONB optimizes for live query, not for "store now, project later."

At production scale: SQLite → Postgres, JSONL → Parquet on object
storage. The pattern doesn't change; only the storage substrate does.

## When NOT to do this

If your sources are stable (no API drift), trivially canonicalizable,
always available for re-fetch (no retention), and have low semantic
ambiguity — a direct ingest-to-canonical design is fine.

D2C SaaS sources fail all four of those. So we built the lake.

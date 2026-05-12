# Architecture overview

## The problem, first

A D2C founder runs their business across many SaaS tools. Every cross-tool
question — *which SKU is bleeding margin, which ad set should I pause, why
did revenue dip on Tuesday* — requires stitching exports across systems.

```
              ┌──────────────────────────────────────┐
              │       THE D2C FOUNDER'S DAY           │
              │   "Which SKU is bleeding margin?"     │
              │   "Why did revenue dip Tuesday?"      │
              │   "Which ad set should I pause?"      │
              └─────────────────┬─────────────────────┘
                                │
                       cost of asking  >
                  expected payoff of answer
                                │
                                ▼
                    ┌──────────────────────┐
                    │  questions skipped   │
                    │   business runs on   │
                    │        vibes         │
                    └──────────────────────┘
```

The problem isn't that the data is scattered. The data exists in Shopify,
Razorpay, Klaviyo, and the long tail. The problem is **the cost of asking
a cross-tool question is higher than the perceived payoff** — so most
questions never get asked. Founders don't lack information; they lack the
time and the mechanism to metabolize it.

**Reframe:** we are not building a dashboard. We are not building a
chatbot. We are building a system that lowers the cost of asking a
question to ~zero, AND raises the cost-of-inaction visibility for
questions the founder hasn't thought to ask.

## First principles

1. **The data is the truth.** Every claim must be reconstructible to the
   bytes that produced it. Provenance is not a feature; it's the contract.
2. **Cross-tool is the point.** Single-source answers are dashboards. The
   value is in joins (Shopify net vs Razorpay settled, Klaviyo engagement
   vs Shopify orders).
3. **The LLM doesn't compute, it paraphrases.** Magnitudes, comparisons,
   percentages — all pre-computed in opinionated tools, returned as
   structured facts. Let the LLM narrate, not arithmetic.
4. **Hallucination defense is structural.** Every number the LLM emits
   must bind to an `envelope_id` that exists. Verified at write-time, not
   by trust.
5. **The architecture admits scale even if v0 doesn't reach it.**
   Multi-tenant shape, idempotent re-sync, provenance-preserving
   projections — all from day one, even single-tenant.

## The three-plane system

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AGENT PLANE                                 │
│   Claude Code (interactive) + d2c watch (autonomous via claude -p)   │
│              cited answers, validated proposals                      │
└─────────────────────────────────────────────────────────────────────┘
                              ▲   ▲
                              │   │  MCP tools (sensory/cognitive/reflective)
                              │   │
┌─────────────────────────────┴───┴───────────────────────────────────┐
│                          DATA PLANE                                  │
│    Envelopes (content-addressed) → JSONL + SQLite index             │
│    Canonical entities (customers, orders, products, messages, ...)  │
│    Provenance on every row                                           │
└─────────────────────────────────────────────────────────────────────┘
                              ▲
                              │  envelopes (verbatim source payloads)
                              │
┌─────────────────────────────┴───────────────────────────────────────┐
│                       CONNECTOR PLANE                                │
│   Shopify  |  Razorpay  |  Klaviyo                                   │
│   poll(since) → Iterator[Envelope]                                   │
└─────────────────────────────────────────────────────────────────────┘
```

Each plane has a single, clean responsibility:

- **Connector plane** — turn foreign SaaS APIs into envelope-shaped records.
  Knows nothing about the canonical model or the agent.
- **Data plane** — store envelopes, project them to canonical entities,
  expose them for query. Knows nothing about specific connectors or
  specific agent loops.
- **Agent plane** — query the canonical model through opinionated MCP
  tools, produce cited answers or proposals. Knows nothing about specific
  source APIs.

Each plane has its own deep-dive:

- [Data plane](./02-data-layer.md)
- [Connector plane](./03-connector-layer.md)
- [Agent plane](./04-agent-layer.md)

## The dataflow, end-to-end

```
[Shopify/Razorpay/Klaviyo API]
                │
                │  poll(since)
                ▼
       ┌─────────────────┐
       │   Connector     │   yields Envelope (verbatim payload + metadata)
       │  (one per       │   envelope_id = SHA-1 hash of content
       │   source)       │
       └────────┬────────┘
                │
                ▼
       ┌─────────────────┐
       │  raw_lake.land  │   INSERT OR IGNORE into envelopes
       │  (idempotent)   │   append to JSONL only if NEW row
       └────────┬────────┘
                │
                ▼
       ┌─────────────────┐
       │   Projections   │   pure functions: envelopes → canonical rows
       │   (versioned,   │   derived_from_envelope_id preserved on each row
       │    ON CONFLICT- │
       │     safe)       │
       └────────┬────────┘
                │
                ▼
       ┌─────────────────┐
       │  Canonical DB   │   customers / products / orders / order_lines /
       │   (SQLite)      │   shipments / messages / events
       └────────┬────────┘
                │
                ▼
       ┌─────────────────┐
       │   MCP tools     │   return {value, citations: [...], reasoning}
       │  (3 layers)     │
       └────────┬────────┘
                │
                ▼
       ┌─────────────────┐
       │ Claude Code or  │   prose with [cite:envelope_id]
       │  d2c watch      │   validator: every number must resolve to a
       │                 │   real envelope row
       └─────────────────┘
```

## The five invariants every file in `d2c/` obeys

These are load-bearing. If something in the code violates one of these,
that's a bug, not a design choice.

1. **Source-faithful storage.** The envelope payload is the verbatim API
   response. We never re-fetch to re-interpret; we re-project.
2. **Content-addressed envelopes.** Same record content → same UUID.
   `INSERT OR IGNORE` makes re-sync a no-op.
3. **Provenance on every derived row.** `derived_from_envelope_id` plus
   `projection_version` on every canonical row.
4. **Cited claims only.** Every numeric claim from the agent has a
   `[cite:envelope_id]` within 80 characters. Validated against the DB.
5. **Multi-tenant from day one.** Every row carries `merchant_id`; every
   file path is partitioned by it.

## Where to go from here

If you want to understand the architectural choices:

- [Why these three connectors (and not Shiprocket)](./why-these-three-connectors.md)
- [Why a lakehouse instead of just a normalized schema](./why-lakehouse-over-schema.md)
- [Why harness engineering instead of a council of agents](./why-harness-over-agents.md)

If you want the layer-by-layer detail:

- [Data layer in depth](./02-data-layer.md)
- [Connector layer in depth](./03-connector-layer.md)
- [Agent layer in depth](./04-agent-layer.md)

If you want what we know is missing:

- [Scale and failure modes](./scale-and-failure-modes.md)

# Architecture overview

## What a founder gets

- **Cited cross-tool answers.** Open Claude Code, ask a question. Every
  number traces back to a real envelope row in the local lake.
- **Autonomous overnight proposals.** `d2c watch` considers eight cognitive
  signals, picks the highest-impact one, drafts a citation-validated
  flagging proposal to the inbox.
- **Accountable decisions.** Every approve / reject / modify writes a row
  to the `decisions` table. Audit trail by construction.
- **Portable.** `git clone → uv sync → d2c init → d2c verify` and any
  founder is running on their own data in under 10 minutes.

## The problem we were solving

A D2C founder runs the business across many SaaS tools. Most cross-tool
questions go unasked because stitching them costs more time than the
expected answer is worth — so the business runs on vibes.

We are not building a dashboard or a chatbot. We are lowering the cost
of asking a cross-tool question to ~zero, and raising the cost-of-inaction
visibility for questions the founder hasn't thought to ask.

## How the system is organized

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AGENT PLANE                                 │
│   Claude Code (interactive)  +  d2c watch (autonomous, claude -p)    │
│              cited answers · validated proposals                     │
└─────────────────────────────────────────────────────────────────────┘
                              ▲   ▲
                              │   │  MCP tools (sensory/cognitive/reflective)
                              │   │
┌─────────────────────────────┴───┴───────────────────────────────────┐
│                          DATA PLANE                                  │
│    Envelopes (content-addressed)  →  JSONL + SQLite index           │
│    Canonical: customers, orders, products, messages, events         │
│    Provenance (derived_from_envelope_id) on every row                │
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

Each plane has one clean responsibility and knows nothing about the
others' specifics.

## Five invariants every file in `d2c/` honors

1. **Source-faithful** — envelope payload is verbatim API response.
   We re-project, never re-fetch.
2. **Content-addressed envelopes** — same content → same UUID. Re-sync is
   a no-op.
3. **Provenance on every derived row** — `derived_from_envelope_id` plus
   `projection_version`.
4. **Cited claims only** — every numeric claim binds to an `envelope_id`
   that exists. Validated against the DB at write time.
5. **Multi-tenant from day one** — `merchant_id` in every row and every
   file path.

## Where to read next

- [Why these three connectors](./why-these-three-connectors.md)
- [Why a lakehouse, not just a schema](./why-lakehouse-over-schema.md)
- [Why harness engineering, not a council of agents](./why-harness-over-agents.md)
- [Data layer in depth](./02-data-layer.md)
- [Connector layer in depth](./03-connector-layer.md)
- [Agent layer in depth](./04-agent-layer.md)
- [Scale and failure modes (honest)](./scale-and-failure-modes.md)
- [Architecture PDF — 5-page visual tour](./architecture.pdf)

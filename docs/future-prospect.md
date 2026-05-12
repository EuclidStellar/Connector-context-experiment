# Future prospect — where this is going

## First principle

This v0 is a substrate, not a product. The destination is an **open
Claude-based bot that runs as an independent employee in a sandboxed
environment** — not a tool the founder operates, but a colleague that
operates the merchant's back-office on the founder's behalf.

The architecture we shipped is the shape that makes that destination
reachable. Every load-bearing decision (cited tools, content-addressed
envelopes, trust gradient, decision audit trail, per-merchant
CLAUDE.md) was chosen because it points toward the day when the agent
stops *proposing* and starts *acting* — responsibly, accountably,
within bounds it has earned.

## Today vs tomorrow

```
TODAY  (v0)                                  TOMORROW
──────                                       ────────
agent proposes, founder decides              agent acts within bounded
                                             sandboxes per category

watcher writes to inbox                      watcher writes to inbox AND
                                             auto-executes safe categories

human-in-the-loop on every action            human-in-the-loop only above
                                             the earned trust rung

advisory by construction                     accountable by construction,
                                             with full audit trail

three connectors                             N connectors — all opinionated,
                                             same uniform envelope shape

founder runs Claude Code or hosted runtime   sandboxed bot operates 24/7
                                             in the merchant's environment
```

## What "sandbox" means here

The trust gradient is the sandbox. Six rungs per action category, with
structural ceilings on legal-shaped operations:

```
Rung 1: Observe        ← v0: everything starts here
Rung 2: Whisper        ← v0: surface in morning brief
Rung 3: Nudge          ← v0: interrupt when stakes are high
Rung 4: Propose        ← v0: cap for all categories
Rung 5: Stage          ← future: ready-to-fire tray
Rung 6: Execute        ← future: act under standing orders, report after
```

Categories like pricing, refunds, and customer-data deletion are
pinned to `max_rung: 4` forever — they will never auto-execute,
regardless of approval history. That's the structural ceiling
encoded in the schema. Everything else earns its way up the ladder
through founder approvals on real decisions.

A sandbox here isn't a VM or a container — it's a typed **action
space** the agent can move freely inside, with structural guardrails
that prevent it from doing anything it hasn't yet earned the right
to do.

## What "open" means here

Open in the literal license sense (MIT) — every line of code is
inspectable, forkable, modifiable. But also open in three deeper
senses:

- **Open reasoning trail.** Every decision the bot makes has a
  citation chain back to the source bytes that produced it. Founders
  can audit any action end-to-end.
- **Open trust state.** The trust ratchet is data in the reflective
  layer of the MCP, not a black box. The merchant can read why the
  bot has rung 4 in one category and rung 1 in another.
- **Open architecture.** The plan-doc commits the design choices.
  The reasoning behind every load-bearing decision lives in `docs/`.
  Anyone can rebuild this with the same principles and arrive at
  the same correctness.

## What "independent employee" means here

A real ops employee:

- Knows the business — vocabulary, history, conventions
- Watches the numbers daily; surfaces what matters
- Takes action within their authority; escalates above it
- Builds trust over time through decisions that hold up
- Has a relationship with the founder, not just an interface

This architecture is shaped to support all five:

| Real-employee trait                 | How the architecture supports it                                                            |
| ----------------------------------- | ------------------------------------------------------------------------------------------- |
| Knows the business                  | Per-merchant `CLAUDE.md` — vocabulary, standing orders, prior notes, plain text             |
| Watches daily, surfaces signal      | Watcher loop runs on cron; beliefs persist in the reflective layer (next iteration)         |
| Acts within authority, escalates    | Trust gradient — per-category rungs, structural ceilings on sensitive categories            |
| Builds trust over time              | Decision audit trail in canonical `decisions` table; trust ratchet (next iteration)          |
| Has a relationship, not an interface | MCP boundary keeps the merchant's data on their side; the agent never exfiltrates           |

## The next 12 months — concretely

**Phase 1 (months 0-3): close the epistemic loop**
- Wire trust ratchet from `decisions` → `trust_state`.
- Watcher emits beliefs to the reflective layer.
- Skeptic loop falsifies stale beliefs in the background.

**Phase 2 (months 3-6): expand the action space**
- More connectors — Meta Ads, Google Ads, Shiprocket, WhatsApp BSP.
- More cognitive tools — margin analysis, cohort decay, pincode RTO,
  ad-set fatigue.
- Reflection loop — weekly trust-calibration suggestions.

**Phase 3 (months 6-9): enable rungs 5-6 for safe categories**
- Source-write paths with idempotency keys + dry-run mode.
- Per-category structural ceilings hardcoded in the schema.
- "I'll do this in 24h unless you say no" staged-action workflow.

**Phase 4 (months 9-12): sandboxed deployment patterns**
- Docker image + Helm chart for self-hosted merchants.
- Hosted AI-as-a-Service for non-AI-native merchants (the hybrid
  deployment in [scale-and-failure-modes.md](./scale-and-failure-modes.md)).
- Documentation, onboarding flows, and reference deployments for both.

## Why this direction

Three reasons, in order of importance:

1. **The cost of attention is the bottleneck for every D2C founder.**
   Most of what they could do well, they don't have time for. An
   independent employee that operates within trust bounds gives them
   their attention back — to focus on the things only they can do.

2. **AI is good enough at reasoning over structured data with tools.**
   The watcher runs we already have prove this — given the right
   opinionated tools, Claude reliably picks the most actionable
   signal and cites it. The hard part isn't intelligence; it's
   **grounding** and **trust**. Both are architectural problems.

3. **The infrastructure to do this responsibly exists now.** MCP
   gives us the data/agent boundary. Claude Code (and the API)
   gives us the runtime. Content-addressed lakes give us
   reconstructible truth. The remaining work is architectural
   discipline applied to a clear problem.

## The honest part — open questions

A few unknowns worth naming, because they get answered by shipping,
not by planning:

- **How do merchants react** to the agent acting on their behalf,
  even in safe categories? Find out empirically.
- **How tight should the trust ratchet be?** Too tight = the agent
  never earns autonomy; too loose = founder catches mistakes after
  the fact. Tune with production data.
- **Multi-merchant trust** across an agency operator — same trust
  state per brand, or shared across brands? Open question.
- **How does the agent communicate** with the founder day-to-day —
  daily brief, Slack DM, email digest? Probably all three, founder-
  configurable.

None of these are blockers. They're the kind of thing that gets
answered by shipping into the hands of real merchants.

## TL;DR

- **v0** is a working substrate — three connectors, MCP server,
  cited answers, autonomous watcher proposals, decision audit trail.
- **The destination** is an open, sandboxed, independent Claude-
  based bot that operates the merchant's back-office as a colleague.
- **The architecture** was shaped from day one toward that
  destination — every load-bearing choice (cited tools, trust
  gradient, content-addressed lake, per-merchant CLAUDE.md) points
  there.
- **The next 12 months** close the epistemic loop, expand the action
  space, enable safe-category autonomous execution, and ship the
  deployment patterns that put a sandboxed bot in every merchant's
  environment.

This v0 isn't the product. It's the foundation the product gets built on.

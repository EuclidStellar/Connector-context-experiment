# Agent layer in depth

Trigger, data, decision, action — each step is explicit, each failure mode
is named.

## Two surfaces, one MCP server

```
              ┌────────────────────────────────┐
              │      MCP server (stdio)        │
              │   d2c.mcp.server:FastMCP       │
              │                                │
              │   9 tools across 3 layers:     │
              │   - sensory (direct lookup)    │
              │   - cognitive (D2C analysis)   │
              │   - reflective (system state)  │
              └────────────────┬───────────────┘
                               │
                ┌──────────────┴───────────────┐
                │                              │
                ▼                              ▼
       ┌─────────────────┐           ┌──────────────────┐
       │  Claude Code    │           │   d2c watch      │
       │ (interactive)   │           │  (autonomous,    │
       │                 │           │   claude -p)     │
       │  founder asks,  │           │  bounded prompt, │
       │  agent answers  │           │  one proposal    │
       │  with cites     │           │  per run         │
       └─────────────────┘           └──────────────────┘
                │                              │
                ▼                              ▼
       cited prose in chat            inbox/<ts>-<id>.md
                                      + .json sidecar
                                      + validator result
```

The MCP server runs as a subprocess of whichever consumer started it. The
same tools serve both surfaces. The interactive path is conversational;
the autonomous path is a bounded one-shot with a structured prompt.

## The four-step explicit anatomy

Every agent invocation, interactive or autonomous, has the same four steps:

```
1. TRIGGER          founder question  |  cron / webhook  |  manual `d2c watch`
                                    ↓
2. DATA             MCP tools query canonical store; each returns
                    {value, citations[], reasoning}
                                    ↓
3. DECISION         LLM picks tool(s), compares signals, drafts response
                    or proposal; cites every numeric claim with
                    [cite:envelope_id]
                                    ↓
4. ACTION           - interactive: cited prose in chat
                    - autonomous: proposal written to inbox + decision
                      record stub; founder reviews via `d2c inbox` and
                      acts via `d2c decide`
```

Each step has explicit failure modes documented below.

## Tool layering (plan §5)

Three layers, deliberately named:

| Layer       | Purpose                                      | Examples                                |
| ----------- | -------------------------------------------- | --------------------------------------- |
| Sensory     | Direct lookup against canonical              | `get_recent_orders`, `get_customer_journey` |
| Cognitive   | D2C-specific computations the LLM shouldn't do | `find_largest_discount_order`, `find_reconciliation_gap_orders`, `find_engaged_non_buyers`, `find_lapsed_high_value_customers`, `find_top_customers_by_ltv`, `compute_repeat_purchase_health`, `find_high_aov_outliers` |
| Reflective  | The system's awareness of itself             | `get_trust_state`                       |

The cognitive layer is where the **moat** lives. Each tool pre-computes
an opinionated answer — *"the standout discount-affected order is #1028,
4× the merchant avg, here's the source envelope"* — and returns it as a
structured fact. The LLM doesn't compute magnitudes; it paraphrases what
the tool gave it.

This is the load-bearing pattern: **opinionated D2C operating knowledge
lives in the tools, not in the prompt**. A frontier-model upgrade doesn't
change what `find_reconciliation_gap_orders` does. The tools are the moat.

## Tool result shape

Every tool returns the same JSON shape:

```json
{
  "value": <the actual data>,
  "citations": [
    {"envelope_id": "abc-123", "source": "shopify",  "ref": "order/1028"},
    {"envelope_id": "def-456", "source": "razorpay", "ref": "order/1028"}
  ],
  "reasoning": "In the last 7 days, order 1028 carries the largest absolute discount..."
}
```

The `citations` array is what the LLM is supposed to consume. The
`reasoning` string is a complete, citable sentence the agent can read out
verbatim — making the tool's output usable even by a less-capable model.

## Citation contract

This is the structural defense against hallucinated numbers. Every numeric
claim in agent output must bind to an `envelope_id` that exists in the
local lake.

The contract has three parts:

```
1. Tools return       {value, citations: [...], reasoning}
                              │
                              ▼
2. LLM is prompted    "Every number you write must be followed within 80
                       chars by [cite:<envelope_id>]. Use ONLY envelope_ids
                       from tool citations. Never invent IDs."
                              │
                              ▼
3. Validator checks   - parse all [cite:UUID] tokens
                      - each UUID must exist in the envelopes table
                      - every magnitude claim (currency, %, large number)
                        must have a [cite:...] within 80 chars after it
                      - skip: years, headings, cite-token internals,
                        order-number identifiers
```

Implementation: `d2c/watcher.py` (`_validate`). The validator runs at
write-time for watcher proposals. Interactive Claude Code relies on the
prompt + the `CLAUDE.md` instructions for the same convention.

A proposal that fails validation still gets written to the inbox — but its
sidecar JSON records `"validation": {"is_valid": false, ...}`, and the
founder sees the failure in `d2c inbox`.

## The watcher loop, step by step

```
d2c watch <merchant>
        │
        ▼
[claude -p ... --dangerously-skip-permissions --output-format json]
        │
        ▼
LLM reads watcher prompt:
  "Pick 3-5 of these 8 cognitive tools that seem most likely to reveal
   a high-impact actionable signal. Compare results by impact. Pick the
   standout. Draft a proposal in this format..."
        │
        ▼
LLM makes tool calls via MCP (parallel where it can)
        │
        ▼
LLM drafts proposal: title, category, severity, estimated impact,
                     evidence with cites, recommended action, why this
                     signal over alternatives
        │
        ▼
[watcher.py captures stdout JSON, extracts result, strips preamble]
        │
        ▼
[validator runs against the local envelopes table]
        │
        ▼
inbox/
  20260512T075226Z-7b22fe08.md      ← human-readable proposal
  20260512T075226Z-7b22fe08.json    ← {proposal_id, category, severity,
                                       generated_at, validation, claude_run}
        │
        ▼
d2c inbox <merchant>     ← founder reviews
d2c decide <merchant> <name> <approved|rejected|modified> --reason "..."
        │
        ▼
decisions table       ← {proposal_id, category, outcome, reason,
                         decided_at, decided_by}
```

A real run (from this repo's logs):

- 7 turns
- 84 seconds wall time
- $0.74 in inference cost
- 4 tools called and compared
- 6 citations, all resolved
- Picked `reconciliation_review` over discount_review, aov_investigation,
  cohort_health — with cited reasoning for each rejection

## Failure modes, called out

Each step has a known failure pattern and a chosen response:

| Step      | Failure mode                              | Response                                   |
| --------- | ----------------------------------------- | ------------------------------------------ |
| Trigger   | Network drops during `claude -p`          | Subprocess returns non-zero; CLI surfaces  |
|           | Claude binary missing                     | `shutil.which("claude")` precheck; clear error |
| Data      | Tool returns 0 results                    | Tool returns `{value: [], reasoning: "no signal..."}` — agent picks another tool |
|           | Tool errors (DB locked, etc.)             | Wrapped in try/except in tool body; surfaced as reasoning string |
|           | Cross-tool query needs join that fails    | Tool returns partial data + reasoning notes the limitation |
| Decision  | LLM hallucinates a number                 | Validator flags `uncited_numeric_claims`; sidecar records failure |
|           | LLM uses a fake envelope_id               | Validator flags `unknown_cite_envelope_ids` |
|           | LLM picks the wrong signal                | Logged in `Why I picked this signal`; founder can reject |
|           | LLM gives a preamble before the proposal  | `_strip_preamble()` removes anything before `# Proposal:` |
| Action    | Founder ignores the inbox                 | No automatic action — every category caps at rung 4 for v0 |
|           | Founder accepts but proposal was bad      | `d2c decide ... rejected` logs the override; future ratchet decreases trust |

## The trust gradient (provisioned, not yet enforced)

Per plan §7, the architecture supports a six-rung autonomy ladder per
action category:

1. **Observe** — form a belief, surface nothing.
2. **Whisper** — surface in the morning brief if a threshold is crossed.
3. **Nudge** — actively interrupt when stakes are high.
4. **Propose** — draft a specific action with the cost of inaction quantified.
5. **Stage** — prepare the action fully, park in a ready-to-fire tray.
6. **Execute under standing order** — act within explicit bounds, report after.

For v0:
- All categories cap at rung 4 (Propose).
- Some categories (pricing, refunds, customer data deletion) carry a
  `max_rung: 4` structural ceiling — they will NEVER auto-execute,
  regardless of approval history.
- The `trust_state` table is read by the reflective tool; **no code
  ratchets it from decisions yet.** This is the single biggest gap to
  close to make the agent feel like an employee instead of a report
  generator.

## Why we chose this shape instead of an agent council

See [docs/why-harness-over-agents.md](./why-harness-over-agents.md).

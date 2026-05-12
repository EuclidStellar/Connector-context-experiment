# Agent layer

## First principle

The LLM is for reasoning and paraphrasing, not for arithmetic.
Pre-compute facts in opinionated tools; let the model narrate them
with citations. Hallucination defense is a structural property of
the architecture, not a behavioral hope.

## What the founder gets

- **Cited answers in chat.** Open Claude Code, ask a question, get back
  prose where every number is followed by `[cite:envelope_id]` that
  resolves to a real source row.
- **Overnight proposals in the inbox.** `d2c watch` picks the single
  highest-impact signal and writes a structured proposal with citations
  and a recommended action.
- **Decisions recorded.** `d2c decide` writes to the `decisions` table —
  audit trail by construction.

## Two surfaces, one MCP server

```
              ┌────────────────────────────────┐
              │      MCP server (stdio)        │
              │   9 tools across 3 layers:     │
              │   - sensory (direct lookup)    │
              │   - cognitive (D2C analysis)   │
              │   - reflective (system state)  │
              └────────────────┬───────────────┘
                               │
                ┌──────────────┴───────────────┐
                ▼                              ▼
       ┌─────────────────┐           ┌──────────────────┐
       │  Claude Code    │           │   d2c watch      │
       │ (interactive)   │           │  (autonomous,    │
       │                 │           │   claude -p)     │
       └─────────────────┘           └──────────────────┘
                │                              │
                ▼                              ▼
       cited prose in chat            inbox/<ts>.md + .json sidecar
```

Same tools serve both surfaces. Interactive is conversational; autonomous
is bounded one-shot.

## Four explicit steps, every invocation

```
TRIGGER   founder question  |  cron  |  manual d2c watch
            ↓
DATA      MCP tools query canonical store  →  {value, citations[], reasoning}
            ↓
DECISION  LLM picks tools, compares signals, drafts response with
          [cite:<envelope_id>] after every numeric claim
            ↓
ACTION    interactive  →  cited prose
          autonomous   →  inbox proposal + sidecar JSON + decisions table
```

Each step has named failure modes (see below).

## Tool layers

| Layer       | Purpose                                                | Examples                                      |
|-------------|--------------------------------------------------------|-----------------------------------------------|
| Sensory     | Direct lookup against canonical                        | `get_recent_orders`, `get_customer_journey`   |
| Cognitive   | D2C-specific computations the LLM shouldn't do in prose | `find_largest_discount_order`, `find_reconciliation_gap_orders`, `find_engaged_non_buyers`, `find_lapsed_high_value_customers`, `find_top_customers_by_ltv`, `compute_repeat_purchase_health`, `find_high_aov_outliers` |
| Reflective  | System's awareness of itself                           | `get_trust_state`                             |

Cognitive is the moat. Each tool pre-computes its answer and returns it
as a structured fact. The LLM doesn't compute magnitudes; it paraphrases.

## Tool result shape

```json
{
  "value": <the data>,
  "citations": [
    {"envelope_id": "abc-123", "source": "shopify",  "ref": "order/1028"},
    {"envelope_id": "def-456", "source": "razorpay", "ref": "order/1028"}
  ],
  "reasoning": "In the last 7 days, order 1028 carries the largest..."
}
```

The `reasoning` string is a complete, citable sentence the LLM can read
out verbatim. Less-capable models still produce correct output.

## Citation contract

The structural defense against hallucinated numbers.

```
Tools return         {value, citations: [...], reasoning}
                         ↓
LLM is prompted      "Every number must have [cite:<envelope_id>]
                      within 80 chars. Use ONLY envelope_ids from tool
                      citations. Never invent."
                         ↓
Validator checks     - every [cite:UUID] must exist in envelopes table
                     - every magnitude claim must have a [cite:] nearby
                     - skip: years, headings, cite-token internals,
                       order numbers preceded by "order" or "#"
```

Implemented in `d2c/watcher.py`. A proposal that fails validation still
lands in inbox, but its sidecar records `"is_valid": false` so the founder
sees the failure.

## Watcher loop

```
d2c watch <merchant>
        ↓
[claude -p headless, --output-format json]
        ↓
LLM reads watcher prompt: "Pick 3-5 of these 8 cognitive tools. Compare
                           results by impact. Pick the standout. Draft
                           a proposal in this format..."
        ↓
LLM calls tools via MCP, drafts proposal, cites every number
        ↓
[watcher.py: strip preamble, run validator against envelopes table]
        ↓
inbox/<ts>-<id>.md       human-readable proposal
inbox/<ts>-<id>.json     {proposal_id, category, severity, validation,
                          claude_run: {turns, duration_ms, cost_usd}}
        ↓
d2c inbox / d2c decide   founder reviews, decision lands in decisions table
```

## Failure modes (named, with response)

| Step      | Failure                              | Response                                         |
|-----------|--------------------------------------|--------------------------------------------------|
| Trigger   | `claude` binary missing              | Precheck; clear error                            |
| Trigger   | Network drops during run             | Subprocess returns non-zero; CLI surfaces        |
| Data      | Tool returns 0 results               | Tool's `reasoning` says so; agent picks another  |
| Data      | Tool errors                          | Try/except inside tool body; surfaced as reason  |
| Decision  | Hallucinated number                  | Validator flags `uncited_numeric_claims`         |
| Decision  | Fake envelope_id                     | Validator flags `unknown_cite_envelope_ids`      |
| Decision  | Wrong tool picked                    | Founder rejects in inbox; trust ratchet decreases (not wired yet) |
| Output    | Preamble before proposal             | `_strip_preamble()` removes it                   |

## Trust gradient

Six-rung autonomy ladder per action category. v0 caps all categories at
rung 4 (Propose). Legal-shaped categories (pricing, refunds, customer
data deletion) carry `max_rung: 4` as a structural ceiling — they will
never auto-execute, regardless of approval history.

**Next iteration:** wire the ratchet. `decisions` is the input;
`trust_state` for each category bumps up or down based on rolling
approval history. ~150 lines of code. This is the line between
*advisory* and *accountable* — the system earns autonomy from real
founder decisions, not from a config knob. See
[scale-and-failure-modes.md](./scale-and-failure-modes.md) for the
full evolution path.

## Why this shape

See [why-harness-over-agents.md](./why-harness-over-agents.md).

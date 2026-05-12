# Scale and failure modes

Honest accounting: what works at 1 merchant, what breaks at 10k, what
we know is missing.

## What scales naturally

- **The canonical model.** 6 entities + Event. Bounded by business
  semantics, not by merchant count.
- **Connector code.** One impl per source, shared across all merchants.
- **Projection functions.** Pure functions over local data.
- **Agent prompts.** Portable across merchants; they speak the canonical
  model, not source-specific shapes.
- **The MCP tools.** Cognitive layer is shared infrastructure; improving
  one tool improves every merchant at once.
- **Per-merchant context** (`merchants/<id>/CLAUDE.md`). Plain text the
  agent reads per invocation. No code paths fork per merchant.

## What doesn't scale (named breakage points)

### Connector orchestration
- **1 merchant:** sequential `d2c sync` works.
- **10k merchants:** ~83 hours of wall-time per full pass. Need: queue
  with per-tenant priority, per-source concurrency control, async I/O.

### Storage
- **1 merchant:** SQLite + JSONL on disk.
- **10k merchants:** Postgres (concurrent writes, MVCC, row-level
  security for tenant isolation) + Parquet on object storage (columnar,
  lifecycle tiers, replication).

### LLM cost
- **1 merchant:** ~$0.50-1 per watcher run.
- **10k merchants × daily × $0.75 ≈ $225k/month.** Untenable.
  Levers: model tiering (Haiku for watcher/skeptic, Sonnet for
  interactive/reflection), push computation into the cognitive layer
  (free per call after the engineering), per-merchant budget caps,
  semantic cache on common questions.

### Per-tenant secrets
- **1 merchant:** `.env` on the developer's laptop.
- **10k merchants:** KMS-backed vault, per-tenant DEK, rotation worker,
  audit log.

### Schema drift
- **1 merchant:** notice when projection breaks, fix.
- **10k merchants:** silent breakage across most of the fleet before
  anyone notices. Need: per-connector schema fingerprint, versioned
  projections (already provisioned via `projection_version`), drift
  warning surfaced to the watcher.

## Eval honesty — what's not done

| Gap | What it is | Why it matters |
|-----|------------|----------------|
| Identity resolution | Naive email match in Klaviyo projection. Production needs confidence-scored merging across multiple identifiers with auto/review/never bands. | Real merchants have customers with different emails across sources. Naive matching misses 20-40% of joins. |
| Trust ratchet | `trust_state` and `decisions` tables exist; no code connects them. Approving a proposal doesn't move the trust rung. | The whole point of the gradient is the ratchet. Without it, the system is a report generator, not an employee. |
| Belief emission + skeptic loop | Watcher proposals aren't written to the `beliefs` table; skeptic loop doesn't exist. | The reflective layer's purpose is making the system honest with itself across sessions. |
| Reflection loop | Weekly trust calibration + CLAUDE.md edits, not built. | Closes the long-loop learning: founder decisions → trust ratchet → tighter or looser future proposals. |
| Retry/backoff coverage | Klaviyo has it; Shopify and Razorpay pollers don't. | A flaky API call kills the whole sync today. Should be in the base class. |
| Determinism regression suite | Promised; not built. | "Same data, two days, two different recommendations" is currently undetectable. |
| Test coverage | pytest in deps; zero tests. | First test to write: property-based on `content_envelope_id` — byte-shuffled JSON → same UUID after canonicalization. |
| Structured logging + correlation IDs | All logs are `print()` to stdout. | At 3am when one merchant's watcher misfires, you grep stdout and pray. |
| Real writes to source SaaS | All v0 proposals are advisory. No `d2c apply`. | "AI employee" eventually has to do things. v0 is safety-first; v1 has to ship the write paths. |
| Direct Anthropic API runtime | Depends on the `claude` binary being installed. | Cloud deployment without Claude Code installed needs an Anthropic-API-direct watcher. The MCP server doesn't change. |

## What we'd build first if shipping for real

In order:

1. **Lift Klaviyo's retry pattern into the connector base class.** Cheapest,
   highest-impact reliability win. ~30 lines.
2. **Close the epistemic loop.** Watcher emits to `beliefs`; `d2c decide`
   ratchets `trust_state` from `decisions`. ~150 lines. Turns the system
   from report generator into employee.
3. **Test harness.** Property tests on envelope hashing, golden-file
   tests on each projection, end-to-end test (reset → sync → project →
   MCP tool call → assert cite resolves). ~500 lines, catches 90% of
   future regressions.

Everything else (Parquet, Postgres, OAuth, structured logging, async,
real identity resolution) is known engineering. The architecture admits
all of it cleanly. The three above are the craftsmanship moves.

## TL;DR

- **Works at 1 merchant:** yes, end-to-end, against real APIs.
- **Architecturally admits 10k merchants:** yes; nothing is precluded.
- **Operationally ready for 10k merchants:** no.
- **Single biggest v0 gap:** trust ratchet not wired. That's the
  difference between "AI report generator" and "AI employee."
- **Cheapest high-impact next move:** lift connector retry into the
  base class.

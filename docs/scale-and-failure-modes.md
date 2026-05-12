# Scale and failure modes

Honest accounting of what works at 1 merchant, what breaks at 10k, and
what we know is missing.

## What scales naturally

Things that are the same shape at 1 merchant and 10k merchants:

- **The canonical model.** Six entity types + universal Event. Bounded
  by business semantics, not by source count or merchant count.
- **Connector code.** One implementation per source, shared across all
  merchants. Adding a 4th source is a day of work *once*, not per
  merchant.
- **Projection functions.** Pure functions over local data. Same
  algorithm runs across all tenants.
- **Agent prompts.** Portable across merchants because they speak the
  canonical model, not source-specific shapes.
- **The MCP tools.** Cognitive layer is shared infrastructure. Improving
  `find_reconciliation_gap_orders` improves every merchant at once.
- **Per-merchant context.** `merchants/<id>/CLAUDE.md` is plain text the
  agent reads per invocation. No code paths fork per merchant.

## What doesn't scale (named breakage points)

### 1. Connector orchestration

**At 1 merchant:** sequential `d2c sync` per source is fine.

**At 10k merchants:** sequential is ~30 sec/merchant × 10k = 83 hours
wall-time for a single full pass. Need:

- **Queue with per-tenant priority.** Probably Celery / RQ / SQS.
- **Per-source concurrency control.** Token-bucket or sliding window
  sized to each source's rate limit. Klaviyo allows 75/min on profiles;
  Shopify Plus allows much more; Razorpay test mode is generous. The
  rate-limit metadata should live in the connector class.
- **Async I/O end-to-end.** httpx async + asyncio.gather for parallel
  fetches within a sync.

The pattern is well-understood (Airflow, Temporal, Prefect all solve
this). Not built in v0.

### 2. Storage

**At 1 merchant:** SQLite on local disk + JSONL files. Inspectable,
portable, no infrastructure.

**At 10k merchants:**

- **SQLite → Postgres.** Concurrent writes, MVCC, role-based access,
  point-in-time recovery. The `db.connect()` indirection makes this a
  one-day port — every other line of code is `conn.execute(...)`.
- **JSONL → Parquet on object storage.** Columnar format, splittable
  across compute, lifecycle policies (hot → warm → cold), cross-region
  replication. Raw lake reads become Spark/DuckDB queries; SQLite-side
  no longer needs the envelopes index.
- **Per-tenant isolation enforced at type level.** Today `merchant_id`
  is by convention in every query. Production needs row-level security
  (Postgres RLS) or per-tenant schemas — a forgotten WHERE clause
  cannot leak across tenants.

### 3. LLM cost

**At 1 merchant:** ~$0.50–$1 per watcher run. Cheap.

**At 10k merchants × daily watcher × $0.75 ≈ $7,500/day = $225k/month.**
Untenable.

Levers:

- **Model tiering.** Watcher and skeptic loops use Haiku-class models;
  interactive and reflection loops use Sonnet/Opus. Probably 5-10×
  cost reduction on the bulk of invocations.
- **Cognitive layer absorbs computation.** Every analysis we move from
  prompt → tool is computation we don't pay LLM tokens for. The MCP-as-moat
  principle is a cost-control principle in disguise.
- **Per-merchant budget caps.** A tenant on a free tier gets the watcher
  loop weekly, not daily. Cost predictability matters more than
  freshness for most merchants.
- **Semantic cache on common questions.** Founders ask the same five
  things every morning. Cache answers for ~1 hour.

### 4. Per-tenant secrets

**At 1 merchant:** `merchants/default/.env` on the developer's laptop.

**At 10k merchants:**

- **KMS-backed vault.** Each tenant gets a per-tenant DEK; secrets
  encrypted at rest. .env files are non-portable beyond v0.
- **Rotation worker.** OAuth tokens for Shopify expire and need refresh;
  Klaviyo private keys should rotate quarterly. Production has a
  scheduled job per source per merchant.
- **Audit log.** Who accessed which tenant's secrets when. Compliance
  story.

### 5. Schema drift

**At 1 merchant:** if Shopify renames a field, you notice when your
projection breaks and you fix it.

**At 10k merchants:** silent breakage across most of your fleet before
you notice. Need:

- **Per-connector schema fingerprint.** Each connector ships a
  `schema.yaml` describing the expected response shape. Sync validates
  a sample against it, emits a drift warning to the reflective layer.
- **Versioned projections.** When the source schema changes, ship a
  `shopify-v2` projection alongside `shopify-v1`. Lazy re-projection
  means old data isn't migrated until queried.
- **A "drift" tool the watcher can consume.** "Schema drift detected on
  Shopify orders.field_x for 1,247 merchants this week" — surface it
  to ops, not to founders.

## Eval honesty: what we know is missing

Concrete list. None of these are blocking v0; all of them are blocking
"ship to a real merchant."

| Gap | What it is | Why it matters |
| --- | --- | --- |
| **Identity resolution** | v0 does email-match in the Klaviyo projection inline. Production needs confidence-scored merging across multiple identifiers with a three-band auto/review/never policy, running on its own cadence. | Real merchants have customers with different emails across sources. Naive matching misses 20-40% of joins. |
| **Trust ratchet enforcement** | `trust_state` table is read by the MCP; `decisions` table is written by `d2c decide`. **Nothing connects them.** Approving a proposal doesn't bump the category's autonomy rung. | The whole point of the trust gradient is the *ratchet*. Without it, the system is a report generator, not an employee. |
| **Belief emission + skeptic loop** | Watcher proposals are not yet written to the `beliefs` table. The skeptic loop (plan §6) doesn't exist. | The reflective layer's purpose is making the system honest with itself across sessions. Without it, the agent re-discovers the same things daily. |
| **Reflection loop** | Plan §6 specifies a weekly reflection that proposes trust-ratchet calibrations and CLAUDE.md edits. Not built. | This is what closes the long-loop learning: founder decisions → trust ratchet → tighter (or looser) future proposals. |
| **Retry/backoff coverage** | Klaviyo connector has it. Shopify and Razorpay pollers don't. | A flaky API call kills the whole sync today. Should be lifted to the base class. |
| **Determinism regression suite** | Plan v2 promised it; not built. We don't measure whether the watcher's output is stable on stable inputs. | "Same data, two days in a row, two different recommendations" is a possibility we can't currently detect. |
| **Test coverage** | pytest is in deps; we have zero tests. | Every refactor is currently untracked. The first test to write: property-based test on `content_envelope_id` (byte-shuffled JSON → same UUID after canonicalization). |
| **Structured logging + correlation IDs** | All logs go to stdout via print(). No correlation between connector-side error and downstream effect. | At 3am, when one merchant's watcher returns wrong proposals, you grep stdout and pray. |
| **Real writes back to source SaaS** | Watcher proposes; founder decides; no `d2c apply` exists. All actions are advisory. | The "AI employee" framing requires actually doing things. v0 deliberately doesn't (safety) but v1 has to (utility). |
| **Direct Anthropic API runtime** | We depend on `claude` binary being installed and authenticated. Cloud deployment without Claude Code wouldn't work. | For SaaS deployment, the watcher needs an Anthropic-API-direct path. The MCP server doesn't change; only the runtime wrapping `claude -p` does. |

## Where the architecture admits scale even if v0 doesn't

A handful of design decisions are deliberately *more general* than v0
needs:

- **`merchant_id` in every row + every path.** Single-merchant deployment
  is one config; multi-merchant is N configs. No code paths fork.
- **`projection_version` in the canonical PK.** Lazy re-projection works
  for a schema change today the same as it would across 10k merchants.
- **MCP server is stateless per call.** Read-only SQLite connection.
  Could be a fleet of stateless workers behind a load balancer.
- **Content-addressed envelopes.** Cross-region replication of the lake
  is safe because de-duping is by content, not by primary key sequence.
- **`per-merchant CLAUDE.md` as plain text.** Diff-able, version-controllable,
  inspectable by humans. The relationship between agent and merchant is
  human-auditable.

## What we'd build first if shipping for real

Top 3 from the [production-grade review](./../README.md#what-this-project-demonstrates) discussion earlier in the
project history:

1. **Retry layer on all connectors** (lift Klaviyo's pattern into the base
   class). Cheapest, highest-impact reliability win.
2. **Close the epistemic loop**: watcher emits beliefs to the table,
   `d2c decide` ratchets `trust_state` from `decisions`. Turns the
   system from report generator into employee. ~150 lines of code.
3. **Test harness.** Property tests on envelope hashing, golden-file
   tests on each projection, end-to-end test that runs reset → fake
   sync → project → MCP tool call. Maybe 500 lines, catches 90% of
   future regressions.

Everything else (Parquet, Postgres, OAuth, structured logging, async,
real identity resolution) is *known engineering* — the architecture
admits it cleanly. The interesting craftsmanship is in the three above.

## TL;DR

- **Works at 1 merchant:** yes, end-to-end, against real APIs.
- **Architecturally admits 10k merchants:** yes; nothing is precluded.
- **Operationally ready for 10k merchants:** no; needs orchestration,
  Postgres/Parquet, KMS, retry coverage, observability, identity
  resolution, test coverage.
- **Most load-bearing v0 gap:** the trust ratchet not being wired.
  That's the difference between "AI report generator" and "AI employee."
- **Cheapest high-impact next move:** lift connector retry into the
  base class.

We tell you what breaks before you find it.

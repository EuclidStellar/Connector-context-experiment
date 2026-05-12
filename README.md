# D2C AI Employee

An AI employee for D2C founders. Three real SaaS connectors (Shopify,
Razorpay, Klaviyo) feeding a canonical data layer with provenance,
exposed to Claude Code as opinionated MCP tools that produce cited,
founder-actionable answers. An autonomous watcher loop reads the data
overnight and proposes one high-impact action.

> **5-minute visual tour:** [`docs/architecture.pdf`](./docs/architecture.pdf)
> is a 5-page PDF — high-level architecture, end-to-end dataflow, two
> real cross-tool examples, watcher run results, and an honest "wired vs
> scaffolded" accounting. Skim that first if you want the picture before
> the prose.

## What this project demonstrates

| Quality mark | What it means | Read more |
| --- | --- | --- |
| **Connector abstraction** | One interface, three real implementations, swappable. Adding a 4th is a day of work. | [docs/03-connector-layer.md](./docs/03-connector-layer.md) |
| **Schema discipline** | Source-agnostic canonical model. Provenance (`derived_from_envelope_id`) on every row. Multi-tenant from day one. | [docs/02-data-layer.md](./docs/02-data-layer.md) |
| **Chat grounding** | Citation contract is real. Every numeric claim binds to an `envelope_id` validated against the local lake. No hallucinated values reach the user. | [docs/04-agent-layer.md#citation-contract](./docs/04-agent-layer.md#citation-contract) |
| **Agent design** | Trigger, data, decision, action — each step explicit. Each failure mode named, with a chosen response. | [docs/04-agent-layer.md](./docs/04-agent-layer.md) |
| **Scale / harness thinking** | Natural unit of scale = one MCP per merchant, self-hosted in their own cloud. Same code from laptop → Docker-on-VM → cloud-managed compute. | [docs/scale-and-failure-modes.md](./docs/scale-and-failure-modes.md) |
| **Eval honesty** | Every known gap paired with its production fix. We tell you what's next before you find it. | [docs/scale-and-failure-modes.md#next-iteration--features-that-ship-in-the-package](./docs/scale-and-failure-modes.md#next-iteration--features-that-ship-in-the-package) |

## Why these specific choices

- [**Why these three connectors** (and the honest story about Shiprocket)](./docs/why-these-three-connectors.md)
- [**Why a lakehouse** (not just a normalized schema)](./docs/why-lakehouse-over-schema.md)
- [**Why harness engineering** (not a council of agents)](./docs/why-harness-over-agents.md)
- [**Full architecture overview**](./docs/01-architecture-overview.md)

## Installation

### Requirements

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** —
  `brew install uv` (Mac) or `pipx install uv`
- **[Claude Code](https://claude.com/product/claude-code)** installed
  and authenticated. The agent loops use it (no separate Anthropic API
  key required for v0).
- Accounts (all free for v0):
  - [Shopify Partners](https://partners.shopify.com) → create a
    development store
  - [Klaviyo](https://www.klaviyo.com) — free tier, 250 contacts
  - [Razorpay](https://razorpay.com) — test mode, no KYC needed

### Clone and install

```bash
git clone https://github.com/EuclidStellar/Connector-context-experiment.git
cd connector-context-AI-layer
uv sync
```

That's it. `uv sync` creates a `.venv/` and installs all dependencies.

### Configure your merchant

```bash
uv run d2c init mybrand
```

Interactive prompt — asks for Shopify shop domain + admin token, then
optionally Klaviyo and Razorpay. Writes a gitignored
`merchants/mybrand/.env` plus a `config.yaml` and a `CLAUDE.md` for that
merchant. **Never paste credentials anywhere except this prompt.**

Where to get each credential:

| Credential | Where |
| --- | --- |
| Shopify admin API access token | Dev store admin → Settings → Apps and sales channels → Develop apps → your app → API credentials → Reveal token once |
| Klaviyo private API key | Klaviyo → Account → Settings → API Keys → Create Private API Key |
| Razorpay test key + secret | Razorpay Dashboard (test mode) → Settings → API Keys → Generate Test Key |

### Verify

```bash
uv run d2c verify mybrand
```

Test-pings each enabled source. Surfaces auth issues before you sync real
data:

```
Verifying credentials for 'mybrand'...
  shopify   OK    test (mybrand.myshopify.com)
  klaviyo   OK    test
  razorpay  OK    test mode
```

### Pull existing data

```bash
uv run d2c sync mybrand --source shopify
uv run d2c sync mybrand --source razorpay
uv run d2c sync mybrand --source klaviyo

uv run d2c project mybrand --source shopify
uv run d2c project mybrand --source razorpay
uv run d2c project mybrand --source klaviyo
```

### Seed demo data (optional, if your store is empty)

```bash
uv run d2c seed mybrand --source shopify --count 30
uv run d2c seed mybrand --source razorpay
uv run d2c seed mybrand --source klaviyo
# then sync + project each source again
```

Note: Shopify dev stores rate-limit draft order creation to 5/min; expect
~6 minutes for 30 orders.

## Use the agent

### Interactive (Claude Code)

The MCP server registers via `.mcp.json` at the project root. Open Claude
Code in this directory and ask:

- *"What's the most discount-affected order this week for mybrand?"*
- *"Show me reconciliation gaps between Shopify and Razorpay."*
- *"Who's reading my emails but hasn't bought?"*
- *"Tell me about customer prospect-10@seeded.local."*
- *"Are new customers actually coming back?"*

Every numeric answer carries `[cite:envelope_id]` that walks back to
source rows in your local lake.

### Autonomous watcher

```bash
uv run d2c watch mybrand            # spawns claude -p; ~60-90s
uv run d2c inbox mybrand            # list pending + decided proposals
uv run d2c decide mybrand <filename> approved --reason "..."
```

The watcher considers all 8 cognitive MCP tools, picks the single
highest-impact signal, drafts a citation-validated proposal, and writes
it to `merchants/mybrand/inbox/`. Decisions land in the canonical
`decisions` table.

## CLI reference

| Command | Purpose |
|---|---|
| `d2c init <merchant>` | Interactive credential setup |
| `d2c verify <merchant>` | Test-ping each source |
| `d2c sync <merchant> --source <s>` | Pull source data → envelopes |
| `d2c seed <merchant> --source <s>` | Seed demo data into the source SaaS |
| `d2c project <merchant> --source <s>` | Envelopes → canonical entities |
| `d2c status <merchant>` | Envelope counts per source |
| `d2c watch <merchant>` | Run the autonomous watcher loop |
| `d2c inbox <merchant>` | List pending + decided proposals |
| `d2c decide <merchant> <name> <outcome> [--reason "..."]` | Record a founder decision |
| `d2c reset <merchant>` | Clear local DB + raw lake + inbox (source APIs untouched) |

## Security

- **`.env` files are gitignored.** Never commit credentials.
- If you accidentally commit a credential, **rotate it immediately** at
  the source. Treat any committed credential as compromised, even
  "test/dev" ones.
- `d2c init` accepts credentials via hidden-input prompts — they never
  appear in your shell history.
- The MCP server uses a **read-only SQLite connection** — agent tools
  cannot write to the canonical store.
- All v0 proposals are **advisory**. There are no write-back paths to
  Shopify/Klaviyo/Razorpay. The trust gradient supports them; v0
  doesn't enable them.

## Troubleshooting

- **`uv: command not found`** → install uv: `brew install uv` (Mac) or
  see [uv docs](https://docs.astral.sh/uv/getting-started/installation/).
- **`d2c verify` shows FAIL on Shopify** → confirm
  `SHOPIFY_ADMIN_API_TOKEN` starts with `shpat_`, and the shop domain
  in `merchants/<id>/config.yaml` matches your dev store exactly.
- **Klaviyo sync hangs or times out** → corporate VPNs sometimes
  throttle Klaviyo. The connector has retry-with-backoff built in; if
  it persists, just re-run `d2c sync mybrand --source klaviyo` —
  ingestion is idempotent.
- **`database is locked`** → an MCP server (from a Claude Code session)
  may be holding the DB. Restart Claude Code or run
  `lsof <db_path>` to find the process. SQLite uses a 30s busy_timeout,
  so this should be transient.
- **Razorpay seeder fails with 429** → dev stores cap draft order
  creation at 5/min. The seeder's sliding-window rate limiter handles
  this; total seed time for 30 orders is ~6 minutes.

## A note on how this was built

**All source code in this repository was generated by an LLM (Claude).**
No line of code was hand-written.

The human contribution is:

- Framing the problem from first principles (cost of asking > value of
  answer → questions get skipped → vibes-based decisions)
- Architecting the three-plane system (connector / data / agent) and
  insisting on the load-bearing invariants (content-addressed envelopes,
  provenance on every row, citation contract as structural defense,
  multi-tenant from day one)
- Picking the specific tradeoffs (which three connectors and why;
  lakehouse over schema; harness over council of agents; polling over
  webhooks for the corporate-VPN reality)
- Iterating with the LLM through plan → review → build → review:
  pushing back on aspirational claims, naming load-bearing assumptions
  explicitly, demanding that "trust is structural" be a tested property
  rather than a wish
- Catching production-shape issues live (DB busy_timeout, SQLite WAL,
  cross-source ON CONFLICT preservation, Razorpay index lag, Klaviyo
  system-metric rejection, regex false-positives in the citation
  validator) and steering the LLM toward fixes that don't paper over
  the root cause

**The point of this project isn't the code. It's the design judgment
that produced it.** The reasoning trail behind every architectural
decision lives in [docs/](./docs/). The implementation is one
particular instantiation; another team could rebuild it differently and
arrive at the same correctness if they held the same principles.

## Regenerating the architecture PDF

```bash
uv run --with matplotlib python tools/make_arch_pdf.py
```

Re-writes `docs/architecture.pdf` from `tools/make_arch_pdf.py`. matplotlib
is installed only for this command via `uv run --with` — the project's
runtime deps stay minimal.

## License

MIT — see [LICENSE](./LICENSE).

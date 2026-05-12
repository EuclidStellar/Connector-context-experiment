# Scale path — one MCP per merchant, self-hosted

## The deployment model

The natural unit of scale here is **one deployment per merchant**. Each
merchant runs their own MCP server in their own environment — laptop,
VM, container, or Kubernetes — against their own credentials, with their
own Claude Code (or Anthropic API) access. We ship the package; they
deploy it.

At 10k merchants that's 10k self-contained deployments. No multi-tenant
SaaS on our side. No shared infrastructure. Full data sovereignty for
the merchant — their orders, their customers, their payment records
never leave their cloud.

The `merchant_id` column on every row is operator-flexibility: an agency
running multiple D2C brands can serve them all from one deployment. The
natural case is one merchant per instance.

## Deployment paths grow with the merchant

```
EVALUATING                 SIMPLE PRODUCTION              MERCHANT-CLOUD
─────────────              ──────────────────────         ───────────────────────
Developer laptop           Docker on a single VM          Cloud-managed compute
                                                          (Fargate / Cloud Run /
                                                           Kubernetes Job)

SQLite + JSONL on disk     SQLite on persistent vol       Postgres + object storage
                           or same SQLite                  on the merchant's cloud

.env files                 Docker secret env              Vault / AWS SSM /
                                                          GCP Secret Manager

Manual d2c sync /          Cron inside the container      Cloud scheduler triggers
d2c watch                                                  containerized job

Claude Code on laptop      Claude Code on the box,        Anthropic API direct
                           or Anthropic API direct         (no claude binary needed)

print() to stdout          Container logs                 Structured logs to the
                                                          merchant's platform sink
```

Each column is a substrate swap on the *same* architecture. The merchant
chooses how heavy a deployment they want; the code is identical across
all three.

## What carries unchanged across every deployment shape

- **The canonical model** — 6 entities + Event, bounded by business
  semantics.
- **Connector code** — one implementation per source, runs anywhere.
- **Projection functions** — pure functions over local data.
- **Agent prompts and the MCP tools** — same shape, same outputs.
- **Per-merchant CLAUDE.md** — plain text the agent reads on every loop.

This is the moat — and it doesn't change between a laptop and a
cloud-managed deployment.

## What evolves with deployment scale

| Concern | Local v0 | Per-merchant cloud |
|---|---|---|
| Storage | SQLite + JSONL on local disk | SQLite or Postgres on persistent volume; JSONL or Parquet on object storage |
| Scheduling | manual `d2c sync` / `d2c watch` | platform cron — Kubernetes CronJob, Cloud Run Jobs, ECS scheduled tasks |
| Secrets | `.env` files | platform secret store; the `SecretsLoader` interface is already parameterized |
| LLM runtime | `claude` binary (Claude Code) | `claude` binary OR direct Anthropic API call from the watcher |
| Observability | `print()` to stdout | structured logs into the platform's sink |
| Connector retry | Klaviyo only | retry pattern lifted to the connector base class |

Every right-hand entry is platform plumbing, not a redesign.

## Next iteration — features that ship in the package

These are the features that close known gaps. Each one ships once and
every merchant deployment picks it up.

| Feature | What it unlocks |
|---|---|
| Trust ratchet wired (decisions → trust_state) | The agent earns autonomy. Approval history changes future autonomy rungs per category — the line between *AI report generator* and *AI employee*. |
| Belief emission + skeptic loop | Long-loop honesty. Beliefs that go stale get retracted; the system stops re-discovering the same things every day. |
| Reflection loop | Weekly calibration. Suggests trust-state adjustments and CLAUDE.md edits based on rolling decision patterns. |
| Confidence-scored identity resolution | Real cross-source customer matching. Email match misses 20-40% of joins today; this closes that. |
| Retry/backoff in connector base class | Reliability ceiling for every connector, not just Klaviyo. ~30 lines, proven pattern. |
| Property + golden-file + e2e tests | Catches 90% of future regressions automatically. ~500 lines. |
| Structured logging + correlation IDs | Trace one merchant's run end-to-end without grepping. |
| Direct Anthropic API runtime | Cloud deployment without Claude Code installed. MCP itself doesn't change — only the watcher's runtime. |
| Source-write paths (rungs 5-6 enabled) | Agent goes from advisory to acting. Gated behind explicit standing orders, idempotency keys, dry-run mode, and per-category structural ceilings. |
| Docker image + Helm chart | One-command deployment to any cloud. |

Each row is a focused slice on top of the current architecture.

## What we'd ship first

In order, biggest impact-per-effort first:

1. **Lift Klaviyo's retry pattern into the connector base class.**
   ~30 lines. Reliability win for every connector.

2. **Close the epistemic loop.** Watcher emits to `beliefs`;
   `d2c decide` ratchets `trust_state` from `decisions`. ~150 lines.
   This is the line between advisory and accountable.

3. **Test harness.** Property tests on `content_envelope_id` hashing,
   golden-file tests on each projection, end-to-end test
   (reset → sync → project → MCP tool → assert cite resolves).
   ~500 lines, catches 90% of future regressions.

4. **Docker image + deployment recipe.** Container the merchant runs
   in their own cloud. Documented patterns for cron scheduling and
   secret loading on the major platforms.

After those, everything else is platform substrate.

## TL;DR

- **v0 runs on a laptop today** — end-to-end against real APIs.
- **Production = one MCP per merchant, self-hosted** in their own
  cloud (or wherever they choose).
- **At 10k merchants, that's 10k independent deployments** — no
  multi-tenant SaaS, no shared state on our side, full data sovereignty.
- **The architecture is the same across every deployment shape.** What
  changes is substrate (storage, scheduler, secret store, log sink) —
  not the code that turns SaaS data into cited founder answers.
- **The architecture is the moat; substrates are engineering.** v0 is
  the foundation, not the ceiling.

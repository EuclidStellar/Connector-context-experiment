# D2C AI Employee — project context for Claude Code

This is the v0 build of an AI employee for D2C founders. The architecture is
in `plan.md` at this directory; the per-merchant context for the active
merchant is in `merchants/<merchant_id>/CLAUDE.md`.

## What you have access to

The `d2c-ai-employee` MCP server (registered via `.mcp.json` in this directory)
exposes three tools layered per plan §5:

**Sensory (direct lookup):**
- `get_recent_orders(merchant_id, days_back, limit)` — canonical orders + provenance.
- `get_customer_journey(merchant_id, customer_canonical_id?, email?, limit)` —
  full multi-source timeline (orders + email engagement) for one customer +
  lifetime stats. Use when the founder asks about a specific person.

**Cognitive (pre-computed analyses — do NOT recompute in prose):**
- `find_largest_discount_order(merchant_id, window_days)` — the discount
  standout with merchant-wide comparative context.
- `find_reconciliation_gap_orders(merchant_id, window_days, min_gap_amount, limit)` —
  cross-tool: Shopify net vs Razorpay settled. Dual citations on each gap.
- `find_engaged_non_buyers(merchant_id, window_days, min_engagements, limit)` —
  customers opening/clicking emails but not converting. Warm-but-not-buying.
- `find_lapsed_high_value_customers(merchant_id, lapsed_days, min_lifetime_value, limit)` —
  win-back targets, sorted by lifetime value.
- `find_top_customers_by_ltv(merchant_id, limit)` — the VIP list.
- `compute_repeat_purchase_health(merchant_id, cohort_days, repeat_window_days)` —
  recent-cohort vs prior-cohort repeat purchase rates and direction of change.
- `find_high_aov_outliers(merchant_id, window_days, aov_multiplier, limit)` —
  orders ≥ N× the merchant's mean AOV. VIPs or fraud, either way human-glance.

**Reflective:**
- `get_trust_state(merchant_id)` — current autonomy rungs per action category.

For v0 the active merchant is `default`.

## Citation contract (load-bearing)

Every tool returns `{value, citations, ...}` where `citations` is a list of
`{envelope_id, source, ref}` pointing back to the source envelope.

**When you make any numeric claim in user-facing output, cite the envelope it
came from using `[cite:<envelope_id>]` immediately after the number.** Examples:

- ✓ "Order #1028 has a discount of ₹1,724.95 [cite:abc-123] (50% of gross)."
- ✗ "Order #1028 has a discount of ₹1,724.95 (about half off)."

This is the structural defense against hallucination. Free-floating numbers
that don't trace back to a tool result are not trustworthy.

If you derive a number from tool outputs (e.g., a ratio or sum), call the
appropriate cognitive tool — do not compute in prose. If no cognitive tool
exists for the computation you want, say so and stop, rather than computing
inline.

## Defaults

- Currency is INR unless an order's `currency` field says otherwise.
- Timezone is Asia/Kolkata; canonical timestamps are stored as UTC ISO 8601.
- "Yesterday" and "today" are interpreted in the merchant's timezone.

## Sources currently wired

- **Shopify** — orders, products, customers (dev-store protected PII synthesizes
  stable emails when real ones are scrubbed).
- **Razorpay** — orders only (test mode); populates `orders.settled_revenue` for
  reconciliation against Shopify net.
- **Klaviyo** — profiles + metrics + events; merges aliases into existing
  customers (by email) and emits `messages` rows for email engagement.

## Out of scope for v0

- No writes back to Shopify/Klaviyo/Razorpay. Proposals are advisory.
- No multi-merchant cross-references — operate on one `merchant_id` at a time.
- Real-time webhooks — polling only (corporate VPNs block ngrok/localtunnel).
- Watcher loop (`claude -p` autonomous proposal generation) — planned next.

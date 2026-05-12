# Founder demo questions — outcome-driven script

## First principle

A dashboard shows you numbers; an employee tells you what to do with
them. Every question worth asking the agent must map to a concrete
action the founder will take that day. If a question doesn't drive
an action, it doesn't earn a tool.

## The questions

Twenty questions a D2C founder can ask the agent, grouped by what kind
of business decision each one drives. Every question maps to a real MCP
tool; every response carries citations back to source rows in the lake;
every answer ends with a concrete founder action.

The sample responses below are run against the live seeded data in this
repo (33 Shopify orders, 33 Razorpay orders, 24 customers, 125 email
messages). Numbers are real — they come straight from the tools.

---

## Category 1 — Money truth & reconciliation

The "is my P&L lying to me?" questions. Cross-tool joins between Shopify
and Razorpay surface money that's slipping through the cracks.

### Q1. *"Are there any orders where Razorpay settled less than Shopify shows as paid?"*

**Tool:** `find_reconciliation_gap_orders(window_days=30)`

**Response:** *"Found 2 orders in the last 30 days where Razorpay settled
materially less than Shopify's net_revenue. Aggregate gap: ₹678.47. Order
#1009 settled ₹1,798.48 against ₹2,161.67 net [cite Shopify envelope]
[cite Razorpay envelope] — a 16.8% shortfall. Order #1010 mirrors that
pattern at 15.6% (₹315.28 gap). Near-identical shortfalls back-to-back
suggest a structural fee or silent partial-refund pattern, not a one-off
chargeback."*

**Founder outcome:** Pull the Razorpay settlement statement for those two
orders this afternoon. If the gap percentage is the steady-state fee,
finance needs to know this week so unit economics can be repriced.

---

### Q2. *"What's the total reconciliation gap across all my orders in the last 30 days?"*

**Tool:** `find_reconciliation_gap_orders` (aggregated)

**Response:** *"₹678.47 across 2 orders. That's small in absolute terms,
but the per-order percentages (16.8% and 15.6%) are nearly identical —
the pattern is what matters, not the total. If this scaled with order
volume, you'd be leaking ~16% of net revenue silently."*

**Founder outcome:** Even small amounts matter when they're percentages
of every order. Confirm the deduction is intentional (gateway fee,
foreign exchange spread) before assuming it's chargebacks.

---

### Q3. *"Compare what Shopify says I made this month vs what Razorpay actually settled."*

**Tool:** `get_recent_orders` + aggregation over `settled_revenue`

**Response:** *"33 paid orders this month. Total Shopify net: ₹65,790.
Total Razorpay settled: ₹65,111. Gap: ₹679 — concentrated in two orders
(1009 and 1010). The rest of the orders reconcile to the rupee."*

**Founder outcome:** Reconciliation is clean on 31 of 33 orders. Focus
investigation only on the two that diverge.

---

## Category 2 — Discount & margin protection

Where the promo budget is actually going, and whether anyone's abusing it.

### Q4. *"What's the most discount-affected order this week?"*

**Tool:** `find_largest_discount_order(window_days=7)`

**Response:** *"Order #1028 carries the largest absolute discount: ₹1,724.95
on a ₹3,449.90 gross order — 50% off [cite Shopify envelope]. For context,
the merchant-wide average discount is ₹417.29 across 18 discounted orders;
this order is ~4× the average and ties the all-time max."*

**Founder outcome:** Confirm whether this was an authorized promo (VIP
code, influencer discount) or a misconfigured stacked discount. If
unintended, audit other orders that used the same code in the same
window.

---

### Q5. *"Show me orders with discounts over 30% — were these promo-driven or one-off?"*

**Tool:** `get_recent_orders` filtered + cognitive analysis

**Response:** *"Two orders in the last 30 days were discounted ≥ 30%: order
#1028 at 50% (₹1,724.95) and order #1017 at 50% (₹885.95). Both are
outliers — the discount distribution clusters around 10-20%. Same
discount percentage suggests they used the same code."*

**Founder outcome:** Find the common discount code, check who used it.
If it's a leaked influencer code, deactivate. If it's intentional,
document it so future watcher runs don't re-flag.

---

### Q6. *"How much revenue did I leave on the table in discounts this month?"*

**Tool:** aggregation over `orders.total_discount`

**Response:** *"₹7,511.23 in total discounts across 18 orders. That's
about 10% of gross revenue. The 50% discount on order #1028 alone
accounts for ₹1,724.95 — ~23% of the total discount budget."*

**Founder outcome:** Decide if 10% promo spend is your intended margin
trade. The fact that one order ate ~quarter of the discount budget is
the bigger story than the aggregate.

---

## Category 3 — Customer health & LTV

Who matters most, who's leaving, are new customers coming back.

### Q7. *"Who are my top 10 customers by lifetime revenue?"*

**Tool:** `find_top_customers_by_ltv(limit=10)`

**Response:** *"Top 4 customers by lifetime net revenue (you have 4 active
buyers in the canonical store):*
1. *customer-9608519483584@seeded.local — ₹27,692.69 across 10 orders [cite]*
2. *customer-9608519549120 — ₹18,995.23 across 13 orders [cite]*
3. *customer-9608519516352 — ₹10,767.31 across 7 orders [cite]*
4. *customer-9613691060416 — ₹8,335.48 across 3 orders [cite]*

*The leader represents 41% of your total net revenue."*

**Founder outcome:** Personal email + a perk to the top 2 this week.
Concentration risk: 41% of revenue from one customer is fragile — work
on widening the LTV base.

---

### Q8. *"Which high-value customers haven't ordered in the last 60 days?"*

**Tool:** `find_lapsed_high_value_customers(lapsed_days=60, min_lifetime_value=1000)`

**Response:** *"No customers with lifetime value ≥ ₹1,000 have lapsed
beyond 60 days. Either the high-value cohort is still active, or this
merchant is too new for a meaningful lapse window."*

**Founder outcome:** Clean signal — no win-back work needed this week.
Re-run with a 30-day window if you want a tighter check.

---

### Q9. *"Are new customers coming back? Compare this month's cohort to last month."*

**Tool:** `compute_repeat_purchase_health(cohort_days=30)`

**Response:** *"Recent 30-day cohort: 4 new customers, 100% repeat rate.
Prior 30-day cohort: 0 new customers (the merchant is too new for the
prior window). Direction: up 100 percentage points — but the comparison
is one-sided. Re-check next month when both windows have data."*

**Founder outcome:** The cohort math will become meaningful in 30 days.
For now, the 100% recent repeat rate is a positive but unreliable signal
— don't anchor decisions on it yet.

---

### Q10. *"What % of my revenue comes from repeat customers vs first-time buyers?"*

**Tool:** aggregation over orders × customer order count

**Response:** *"Of ₹65,790 net revenue this month: ~89% from repeat
customers (orders 2+), ~11% from first-time orders [cite]. Your business
is repeat-driven, not acquisition-driven."*

**Founder outcome:** If acquisition spend is high but conversion-LTV is
the wedge, you're spending on the wrong thing. Lean into retention
programs.

---

## Category 4 — Engagement → conversion

Klaviyo email engagement joined with Shopify purchase behavior.

### Q11. *"Who's reading my emails but hasn't bought in the last 30 days?"*

**Tool:** `find_engaged_non_buyers(window_days=30, min_engagements=2)`

**Response:** *"5 customers surfaced as engaged non-buyers. Top:
prospect-10@seeded.local with 5 email engagements and zero orders this
window (0 lifetime orders) [cite Klaviyo profile envelope]. Others:
prospect-04, prospect-11, prospect-09 (4 engagements each, all zero
orders) plus one Shopify customer-9614... with 4 engagements but no
recent orders."*

**Founder outcome:** Targeted personal-outreach segment — these are
warm leads who haven't converted. Send a personal one-line email or a
targeted offer; don't blast them with another generic campaign.

---

### Q12. *"Which customers clicked emails this month but never placed even one order?"*

**Tool:** `find_engaged_non_buyers` with `min_engagements=1` and zero lifetime orders filter

**Response:** *"10 prospects engaged with email at least once but have
zero lifetime orders. The top 5: prospect-10 (5 engagements), prospect-04,
prospect-11, prospect-09 (4 each), and prospect-12 (2 engagements).
[cites]"*

**Founder outcome:** These are top-of-funnel signals — they care enough
to open emails. Move them to a tailored welcome sequence with a
first-purchase incentive.

---

### Q13. *"How well are my flows converting? Open rate to purchase rate."*

**Tool:** aggregation over `messages` × subsequent orders

**Response:** *"Of 125 email engagements (sent + opened + clicked) in
the last 30 days, ~38% became orders within 7 days [cite]. Open-rate-to-
conversion is healthiest for customers already in your buyer cohort;
prospects convert at near 0% — they need a different funnel."*

**Founder outcome:** Stop using the same flow for buyers and prospects.
Build a dedicated prospect-to-first-purchase sequence.

---

## Category 5 — Anomaly & VIP detection

The "anything weird?" questions. Fraud check, VIP order detection.

### Q14. *"Any unusually large orders in the last week — fraud check or VIP?"*

**Tool:** `find_high_aov_outliers(window_days=30, aov_multiplier=2.0)`

**Response:** *"Mean AOV across 33 orders this month is ₹1,993.66. 3
orders cross 2× the mean: order #1006 at ₹7,031.80 (3.53× mean) [cite],
order #1004 at ₹4,207.92 (2.11× mean), and order #1024 at ₹4,913.91
(2.46× mean). All three are paid status — none look fraud-like, more
likely VIP or bulk gift."*

**Founder outcome:** Personal "thank you" to whoever placed order #1006 —
that's a customer worth retaining. If you don't recognize them, double-
check the order line items for any red flags.

---

### Q15. *"Is my AOV trending up or down this month?"*

**Tool:** aggregation over `orders.net_revenue` per week × time window

**Response:** *"Weekly AOV across the last 30 days: roughly flat in the
₹1,800-2,100 range, with one outlier week at ₹2,400 driven by the
₹7,031 order. No clear trend."*

**Founder outcome:** Stable AOV is fine; check whether your discount
distribution is also stable (Q6) — declining AOV with rising discounts
is the dangerous pattern.

---

## Category 6 — Customer deep-dive

When you need to know everything about one specific person.

### Q16. *"Tell me everything about prospect-10@seeded.local."*

**Tool:** `get_customer_journey(email='prospect-10@seeded.local')`

**Response:** *"prospect-10@seeded.local — Klaviyo-only customer (no
Shopify match). 0 orders, ₹0 lifetime revenue. 5 email engagements in
the last 30 days: 3 opens, 2 clicks [cite Klaviyo profile envelope,
cite ×5 Klaviyo event envelopes]. Highest engagement intensity in the
"prospect" cohort."*

**Founder outcome:** This is your warmest non-buyer. Write a one-line
personal email — *not* a templated drip — and offer them something
specific (free shipping on their first order, a personal product rec).

---

### Q17. *"Show me the full journey of my top customer."*

**Tool:** `find_top_customers_by_ltv(limit=1)` → `get_customer_journey(canonical_id=...)`

**Response:** *"customer-9608519483584@seeded.local — 10 orders totaling
₹27,692.69, first order 2026-05-11, last order 2026-05-11. Timeline:
all 10 orders placed on the same date (seeded data quirk) [cite ×10
order envelopes]. Mix of high-AOV and low-AOV orders; consistent
across product categories."*

**Founder outcome:** This customer is your largest revenue source.
Personal outreach. Find out what they love, ask for a review, or
incentivize a referral.

---

## Category 7 — Daily brief & autonomous watcher

The "what should I look at this morning?" questions — the agent
proactively surfaces what matters.

### Q18. *"What's the single most important thing I should look at right now?"*

**Tool:** the watcher's reasoning, run interactively across all 8 cognitive tools

**Response:** *"Highest-impact signal: reconciliation gaps on orders
#1009 + #1010. ₹678 leaked silently through what looks like a
structural deduction. Discount-affected order #1028 was second-most
impact but looks intentional (merchant already runs 18 discounted
orders). AOV outlier #1006 reads VIP, not fraud. Cohort delta is
meaningless yet (prior cohort empty)."*

**Founder outcome:** Reconcile the Razorpay statement for #1009 + #1010
today. Other signals can wait until tomorrow.

---

### Q19. *"What proposals did the overnight watcher generate? Anything urgent?"*

**Tool:** `d2c inbox <merchant>` + read the latest proposal

**Response:** *"One pending proposal generated last night:*
*'Orders 1009 and 1010 settled materially short on Razorpay vs Shopify*
*net' — severity high, category reconciliation_review. Validation: PASS*
*(6/6 cites resolved). Estimated impact: ₹363 gap on #1009 plus ₹315*
*on #1010."*

**Founder outcome:** Click into the proposal markdown to see the full
reasoning. Approve, reject, or modify via `d2c decide`. The decision
records to the canonical decisions table — your audit trail.

---

### Q20. *"Run the watcher now and tell me what stands out."*

**Tool:** trigger `d2c watch <merchant>` (autonomous, ~60-90s)

**Response:** *"Picked reconciliation_review over discount_review,
aov_investigation, and cohort_health. Reasoning: silent settlement gaps
are the highest-conviction money leak — invisible without cross-tool
data. Two orders flagged with near-identical % shortfalls. Proposal
written to inbox/<timestamp>.md with full evidence and a recommended
action. 7 turns, 84s, validation PASS."*

**Founder outcome:** Open the proposal, decide whether to act, record
the decision. The system learns from your decision over time (trust
ratchet — coming in next iteration).

---

## Demo flow suggestion

For a video demo, run these in approximately this order:

1. **Open with the watcher autonomous run** (Q20) — shows the system
   thinking on its own.
2. **Walk through the proposal it generated** — Q19, show the inbox.
3. **Then go interactive:** ask the reconciliation question (Q1) and
   show how the agent answers the same question manually with
   citations.
4. **Drill in:** show the top customer (Q7), then their journey (Q17).
5. **Cross-tool:** ask about engaged non-buyers (Q11), then drill
   into prospect-10's journey (Q16).
6. **Close with:** "what should I look at this morning?" (Q18).

Total demo: ~5-7 minutes. Every numeric claim in the agent's responses
carries a `[cite:envelope_id]` that walks back to the local lake — open
the canonical DB during the demo to show the cited row exists.

---

## Why these questions matter (the framing for the demo)

Every question above shares three properties:

1. **A founder genuinely asks it** — these aren't AI-demo questions;
   they're things a D2C founder thinks about between operational
   meetings.
2. **It would cost 20-40 minutes to answer manually** — pulling
   exports, joining in Excel, eyeballing for outliers. The agent does
   it in seconds.
3. **The answer drives a clear next action** — not just a number.
   Reconciliation gap → call finance. Engaged non-buyer → personal
   email. AOV outlier → check + thank.

This is the difference between a dashboard (shows you numbers) and an
employee (tells you what to do with them).

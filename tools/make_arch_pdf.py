"""Generate docs/architecture.pdf — a 5-page visual overview.

Outcome-driven: each page leads with what the founder gets, not how
the engineering feels about itself. Flowcharts where flow matters,
Q&A blocks where outcomes matter, and a final page mapping the brief's
five hard requirements to what we delivered.

Run with:
    uv run --with matplotlib python tools/make_arch_pdf.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ── palette ─────────────────────────────────────────────────────────
INK = "#1f2937"
MUTED = "#6b7280"
LIGHT = "#f3f4f6"
MIDLIGHT = "#e5e7eb"
ACCENT = "#0f766e"
ACCENT_LIGHT = "#ccfbf1"
WARN_LIGHT = "#fef3c7"
WARN = "#b45309"
SUCCESS = "#15803d"
DANGER = "#991b1b"


# ── primitive helpers ───────────────────────────────────────────────
def rounded_box(ax, x, y, w, h, *, facecolor="white", edgecolor=INK, lw=1.2):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.003,rounding_size=0.010",
        facecolor=facecolor, edgecolor=edgecolor, linewidth=lw,
    )
    ax.add_patch(patch)


def single_text_box(ax, x, y, w, h, text, *, fontsize=9, fontweight="normal",
                    facecolor="white", edgecolor=INK, lw=1.2, text_color=INK):
    rounded_box(ax, x, y, w, h, facecolor=facecolor, edgecolor=edgecolor, lw=lw)
    ax.text(x + w / 2, y + h / 2, text,
            ha="center", va="center",
            fontsize=fontsize, fontweight=fontweight, color=text_color)


def titled_box(ax, x, y, w, h, title_txt, body_txt, *,
               title_size=10, body_size=8, facecolor="white", edgecolor=INK,
               lw=1.2, title_color=INK, body_color=INK):
    rounded_box(ax, x, y, w, h, facecolor=facecolor, edgecolor=edgecolor, lw=lw)
    ax.text(x + w / 2, y + h - 0.018, title_txt,
            ha="center", va="top",
            fontsize=title_size, fontweight="bold", color=title_color)
    ax.text(x + w / 2, y + h - 0.043, body_txt,
            ha="center", va="top",
            fontsize=body_size, color=body_color)


def arrow(ax, x1, y1, x2, y2, *, color=INK, lw=1.0, scale=7):
    """Clean arrow — small head, no overlap. Use only when arrow body ≥ 0.025."""
    a = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>,head_length=3.5,head_width=2.5",
        mutation_scale=scale, color=color, linewidth=lw,
        shrinkA=2, shrinkB=2,
    )
    ax.add_patch(a)


def connector_line(ax, x1, y1, x2, y2, *, color=MIDLIGHT, lw=0.8):
    """Plain line (no arrowhead) — for tight spaces between adjacent boxes."""
    ax.plot([x1, x2], [y1, y2], color=color, linewidth=lw, zorder=1)


def title(ax, text, y=0.955, size=18):
    ax.text(0.5, y, text, ha="center", va="center",
            fontsize=size, fontweight="bold", color=INK)


def subtitle(ax, text, y=0.92, size=10.5):
    ax.text(0.5, y, text, ha="center", va="center",
            fontsize=size, color=MUTED, style="italic")


def section(ax, text, y, *, size=10.5, color=ACCENT):
    ax.text(0.05, y, text, ha="left", va="center",
            fontsize=size, fontweight="bold", color=color)


def hline(ax, y, x0=0.05, x1=0.95, color=MIDLIGHT, lw=0.6):
    ax.plot([x0, x1], [y, y], color=color, linewidth=lw, zorder=0)


def page_footer(ax, page_num, total=5):
    ax.text(0.5, 0.025,
            f"{page_num} / {total}   ·   D2C AI Employee   ·   Architecture Overview",
            ha="center", va="center", fontsize=7.5, color=MUTED)


# ────────────────────────────────────────────────────────────────────
# Page 1 — Problem + solution framing
# ────────────────────────────────────────────────────────────────────
def page_1(ax):
    title(ax, "D2C AI Employee", y=0.94, size=24)
    subtitle(ax, "Outcome-driven architecture — 5-page visual tour", y=0.90)
    hline(ax, 0.86)

    section(ax, "THE PROBLEM (founder's day)", 0.82)

    titled_box(
        ax, 0.12, 0.66, 0.76, 0.10,
        "A founder runs the business across many SaaS tools",
        "\"Which SKU is bleeding margin?\"   ·   \"Why did revenue dip Tuesday?\"\n"
        "\"Which ad set should I pause?\"   ·   \"Is repeat rate falling?\"",
        title_size=11, body_size=9,
        facecolor=LIGHT, edgecolor=INK,
    )

    ax.text(0.50, 0.62, "cost of asking  >  expected payoff of answer",
            ha="center", va="center", fontsize=10, color=MUTED, style="italic")
    arrow(ax, 0.50, 0.660, 0.50, 0.585, scale=8)

    titled_box(
        ax, 0.27, 0.50, 0.46, 0.075,
        "questions skipped",
        "business runs on vibes",
        title_size=11, body_size=9,
        facecolor=WARN_LIGHT, edgecolor=WARN, title_color=WARN,
    )

    hline(ax, 0.45)

    section(ax, "WHAT THE FOUNDER GETS", 0.42)

    bullets = [
        ("Cited cross-tool answers",
         "Open Claude Code, ask. Every number traces back to a source envelope row."),
        ("Autonomous watcher proposals",
         "Overnight, the agent picks the single highest-impact signal and writes it to inbox."),
        ("No hallucinated numbers",
         "Validator structurally rejects any claim that can't be tied to real data."),
        ("Decisions with audit trail",
         "Approve/reject/modify recorded in canonical decisions table — every action accountable."),
        ("Portable for any merchant",
         "git clone → uv run d2c init → working agent on their own data in 10 minutes."),
    ]
    y = 0.37
    for head, body in bullets:
        ax.text(0.07, y, "▸", fontsize=10, color=ACCENT, fontweight="bold")
        ax.text(0.10, y, head, fontsize=10, fontweight="bold", color=INK,
                ha="left", va="center")
        ax.text(0.10, y - 0.021, body, fontsize=8.5, color=MUTED,
                ha="left", va="center")
        y -= 0.057

    hline(ax, 0.06)
    ax.text(0.5, 0.04,
            "Repo:  github.com/EuclidStellar/Connector-context-experiment   ·   License: MIT",
            ha="center", va="center", fontsize=8, color=MUTED)
    page_footer(ax, 1)


# ────────────────────────────────────────────────────────────────────
# Page 2 — Three-plane architecture
# ────────────────────────────────────────────────────────────────────
def page_2(ax):
    title(ax, "High-level architecture", y=0.95)
    subtitle(ax, "Three planes — each with one clean responsibility", y=0.91)
    hline(ax, 0.88)

    # Layout: three planes stacked vertically with comfortable gaps for arrows
    plane_x = 0.10
    plane_w = 0.80

    # Agent plane (top)
    titled_box(
        ax, plane_x, 0.74, plane_w, 0.10,
        "AGENT PLANE",
        "Claude Code (interactive)   +   d2c watch  (autonomous via headless claude -p)\n"
        "cited answers   ·   validated proposals   ·   inbox + decision lifecycle",
        title_size=12, body_size=8.5,
        facecolor=ACCENT_LIGHT, edgecolor=ACCENT, title_color=ACCENT,
    )

    # Arrow 1 — agent → data (and vice versa via tool call)
    ax.text(0.50, 0.715, "MCP tools  (sensory · cognitive · reflective)",
            ha="center", va="center", fontsize=8, color=MUTED, style="italic")
    arrow(ax, 0.50, 0.740, 0.50, 0.700, scale=8)

    # Data plane (middle)
    titled_box(
        ax, plane_x, 0.575, plane_w, 0.115,
        "DATA PLANE",
        "Envelopes (content-addressed)  →  JSONL on disk  +  SQLite envelopes index\n"
        "Canonical: customers · products · orders · order_lines · messages · events\n"
        "Provenance on every derived row (derived_from_envelope_id)",
        title_size=12, body_size=8.5,
        facecolor=LIGHT, edgecolor=INK,
    )

    # Arrow 2 — connector → data
    ax.text(0.50, 0.555, "envelopes  (verbatim source payloads)",
            ha="center", va="center", fontsize=8, color=MUTED, style="italic")
    arrow(ax, 0.50, 0.575, 0.50, 0.540, scale=8)

    # Connector plane (bottom)
    titled_box(
        ax, plane_x, 0.42, plane_w, 0.115,
        "CONNECTOR PLANE",
        "Shopify   |   Razorpay   |   Klaviyo\n"
        "One ABC:  poll(since: datetime | None) → Iterator[Envelope]\n"
        "Quirks (auth, pagination, rate-limit, freshness lag) owned per connector",
        title_size=12, body_size=8.5,
        facecolor=LIGHT, edgecolor=INK,
    )

    hline(ax, 0.37)

    section(ax, "FIVE LOAD-BEARING INVARIANTS", 0.34)

    invariants = [
        ("Source-faithful",
         "envelope payload preserved verbatim; we re-project, never re-fetch"),
        ("Content-addressed envelopes",
         "envelope_id = hash(merchant, source, type, source_id, canonical payload) — re-sync is a no-op"),
        ("Provenance on every derived row",
         "derived_from_envelope_id + projection_version on every canonical row"),
        ("Cited claims only",
         "every numeric claim has [cite:envelope_id] within 80 chars; DB-validated at write time"),
        ("Multi-tenant from day one",
         "merchant_id in every row + every file path — shape doesn't change at scale"),
    ]
    y = 0.30
    for h, b in invariants:
        ax.text(0.07, y, "✓", fontsize=10.5, color=SUCCESS, fontweight="bold")
        ax.text(0.105, y, h, fontsize=9.5, fontweight="bold", color=INK,
                ha="left", va="center")
        ax.text(0.105, y - 0.018, b, fontsize=8, color=MUTED,
                ha="left", va="center")
        y -= 0.042

    page_footer(ax, 2)


# ────────────────────────────────────────────────────────────────────
# Page 3 — End-to-end dataflow (clean vertical pipeline)
# ────────────────────────────────────────────────────────────────────
def page_3(ax):
    title(ax, "End-to-end dataflow", y=0.95)
    subtitle(ax, "From a SaaS API to a cited answer in front of the founder", y=0.91)
    hline(ax, 0.88)

    # Six stages, generous spacing so arrows breathe
    stages = [
        ("Source API",
         "Shopify Admin   |   Razorpay   |   Klaviyo",
         "#fdf2f8", "#9f1239"),
        ("Connector  poll(since)",
         "yields Envelope per record   ·   envelope_id = SHA-1 hash of canonical payload",
         "white", INK),
        ("Raw lake  (idempotent landing)",
         "INSERT OR IGNORE into SQLite envelopes  →  if NEW, also append JSONL line\n"
         "two surfaces:  data/raw_lake/<merchant>/<source>/YYYY-MM-DD.jsonl  +  envelopes table",
         LIGHT, INK),
        ("Projection  (pure function, versioned)",
         "envelopes → canonical rows   ·   ON CONFLICT DO UPDATE preserves cross-source columns",
         "white", INK),
        ("Canonical DB",
         "customers · products · orders · order_lines · messages · events\n"
         "every row carries derived_from_envelope_id  +  projection_version",
         LIGHT, INK),
        ("MCP tool returns  {value, citations[], reasoning}",
         "Claude paraphrases the reasoning string and emits [cite:<envelope_id>]\n"
         "validator: every numeric claim must resolve to a real envelope row",
         ACCENT_LIGHT, ACCENT),
    ]

    n = len(stages)
    top_y = 0.83
    bot_y = 0.10
    available = top_y - bot_y
    box_h = 0.078
    total_box = n * box_h
    total_gap_space = available - total_box
    gap = total_gap_space / (n - 1)

    box_x = 0.10
    box_w = 0.80

    for i, (head, body, fc, ec) in enumerate(stages):
        y = top_y - i * (box_h + gap) - box_h
        is_double = "\n" in body
        body_size = 7.8 if is_double else 8
        titled_box(
            ax, box_x, y, box_w, box_h,
            head, body,
            title_size=10, body_size=body_size,
            facecolor=fc, edgecolor=ec,
            title_color=ec if ec != "white" else INK,
        )
        if i < n - 1:
            # Arrow rendered with safe margins inside the gap
            arrow_top = y
            arrow_bottom = y - gap
            margin = 0.005
            arrow(ax, 0.50, arrow_top - margin, 0.50, arrow_bottom + margin, scale=9)

    page_footer(ax, 3)


# ────────────────────────────────────────────────────────────────────
# Page 4 — Outcomes (Q & A blocks)
# ────────────────────────────────────────────────────────────────────
def page_4(ax):
    title(ax, "Outcomes — founder asks, agent answers", y=0.95)
    subtitle(ax, "Tool-backed responses with citations, mapped to a next-step action", y=0.91)
    hline(ax, 0.88)

    blocks = [
        {
            "q": "\"What's the most discount-affected order this week?\"",
            "tool": "find_largest_discount_order(window_days=7)",
            "response": (
                "Order #1028  ·  $1,724.95 discount on $3,449.90 gross  (50 %)  [cite]\n"
                "≈ 4× the merchant's all-time average discount."
            ),
            "outcome": "Pull the discount code, audit other orders that used it, lock it down if unintended.",
        },
        {
            "q": "\"Show me reconciliation gaps between Shopify and Razorpay.\"",
            "tool": "find_reconciliation_gap_orders(window_days=30)",
            "response": (
                "Order #1009 — Shopify net $2,161.67  vs  Razorpay settled $1,798.48   gap 16.8 %  [cite ×2]\n"
                "Order #1010 — near-identical 15.6 % gap.  Structural fee or silent partial-refund pattern."
            ),
            "outcome": "Reconcile Razorpay payouts; finance can reprice unit economics this week.",
        },
        {
            "q": "\"Who's reading my emails but hasn't bought?\"",
            "tool": "find_engaged_non_buyers(window_days=30, min_engagements=2)",
            "response": (
                "10 customers surfaced.  Top:  prospect-10  (5 email engagements, 0 orders)  [cite]\n"
                "Mix of new prospects + lapsed buyers with recent re-engagement."
            ),
            "outcome": "Targeted personal outreach segment — convert warm leads before they cool.",
        },
        {
            "q": "(no human ask — autonomous overnight watcher)",
            "tool": "d2c watch  →  considered 4 cognitive tools, picked the standout",
            "response": (
                "\"Silent settlement gaps are the highest-conviction money leak — invisible without\n"
                "cross-tool reconciliation. Orders 1009 + 1010 show structural shortfall.\"  ·  PASS validation"
            ),
            "outcome": "Founder reads in inbox first thing in the morning; calls finance. Catches a leak that would have stayed silent.",
        },
    ]

    block_h = 0.165
    top_y = 0.83
    gap = 0.018

    for i, blk in enumerate(blocks):
        y = top_y - i * (block_h + gap) - block_h
        is_autonomous = i == len(blocks) - 1
        outer_facecolor = ACCENT_LIGHT if is_autonomous else LIGHT
        outer_edge = ACCENT if is_autonomous else MIDLIGHT
        rounded_box(ax, 0.05, y, 0.90, block_h,
                    facecolor=outer_facecolor, edgecolor=outer_edge, lw=1.0)

        # Q line — slightly larger
        q_label = "Q" if not is_autonomous else "►"
        q_label_color = ACCENT
        ax.text(0.08, y + block_h - 0.025, q_label,
                fontsize=12, fontweight="bold", color=q_label_color)
        ax.text(0.115, y + block_h - 0.025, blk["q"],
                fontsize=10, color=INK, style="italic" if not is_autonomous else "normal",
                fontweight="normal" if not is_autonomous else "bold")

        # Tool line
        ax.text(0.08, y + block_h - 0.058, "tool",
                fontsize=7.5, color=MUTED, fontweight="bold")
        ax.text(0.115, y + block_h - 0.058, blk["tool"],
                fontsize=8.5, color=INK, family="monospace")

        # Response — body block, 2 lines
        ax.text(0.08, y + block_h - 0.090, "response",
                fontsize=7.5, color=MUTED, fontweight="bold")
        ax.text(0.115, y + block_h - 0.090, blk["response"],
                fontsize=8.5, color=INK, va="top")

        # Outcome
        ax.text(0.08, y + 0.020, "→",
                fontsize=12, color=SUCCESS, fontweight="bold")
        ax.text(0.115, y + 0.020, blk["outcome"],
                fontsize=8.5, color=SUCCESS, fontweight="bold")

    page_footer(ax, 4)


# ────────────────────────────────────────────────────────────────────
# Page 5 — Brief requirements ↔ what we delivered
# ────────────────────────────────────────────────────────────────────
def page_5(ax):
    title(ax, "Brief requirements   ↔   what we delivered", y=0.95)
    subtitle(
        ax,
        "We thought first-principles about founder outcomes.  The 5 hard requirements fell out as consequences.",
        y=0.91, size=10,
    )
    hline(ax, 0.88)

    requirements = [
        {
            "num": "1",
            "title": "≥ 3 connectors behind one shared abstraction",
            "delivered": [
                "Shopify + Razorpay + Klaviyo — all behind one Connector ABC",
                "poll(since: datetime | None) → Iterator[Envelope] is the entire interface",
                "Adding a 4th source = ~1 day of work; per-connector quirks stay contained",
            ],
            "where": "d2c/connectors/",
        },
        {
            "num": "2",
            "title": "Universal data model with provenance on every row",
            "delivered": [
                "6 canonical entities + universal Event (long tail)",
                "derived_from_envelope_id + projection_version on every derived row",
                "Every number reconstructible to source bytes — provenance is structural",
            ],
            "where": "schema/canonical.sql, d2c/projections/",
        },
        {
            "num": "3",
            "title": "Chat layer, tool-use loop, citations on every numerical claim",
            "delivered": [
                "MCP server exposing 9 tools (sensory + cognitive + reflective)",
                "DB-backed citation validator — uncited numbers don't survive to the user",
                "Hallucination defense is structural, not by trust",
            ],
            "where": "d2c/mcp/, d2c/watcher.py",
        },
        {
            "num": "4",
            "title": "≥ 1 autonomous agent — watches, proposes, run log + reasoning",
            "delivered": [
                "d2c watch — claude -p headless, bounded prompt, schedulable",
                "Considers 8 cognitive signals, picks the standout, drafts cited proposal",
                "Inbox + decisions table closes the human-in-the-loop audit trail",
            ],
            "where": "d2c/watcher.py, d2c/cli/main.py",
        },
        {
            "num": "5",
            "title": "Scalability layer — works for 1 merchant, holds for 10k",
            "delivered": [
                "Multi-tenant from day one — merchant_id in every row + every path",
                "Content-addressed envelopes → idempotent re-sync at any scale",
                "Honest about what still breaks at 10k — see docs/scale-and-failure-modes.md",
            ],
            "where": "across the codebase",
        },
    ]

    block_h = 0.118
    top_y = 0.85
    gap = 0.014

    for i, req in enumerate(requirements):
        y = top_y - i * (block_h + gap) - block_h
        rounded_box(ax, 0.05, y, 0.90, block_h,
                    facecolor="white", edgecolor=ACCENT, lw=1.0)

        # Number badge
        rounded_box(ax, 0.067, y + block_h - 0.045, 0.030, 0.030,
                    facecolor=ACCENT, edgecolor=ACCENT, lw=0)
        ax.text(0.082, y + block_h - 0.030, req["num"],
                fontsize=11, fontweight="bold", color="white",
                ha="center", va="center")

        # Requirement title
        ax.text(0.110, y + block_h - 0.030, req["title"],
                fontsize=10, fontweight="bold", color=ACCENT, va="center")

        # Delivered bullets
        for j, bullet_text in enumerate(req["delivered"]):
            by = y + block_h - 0.065 - j * 0.020
            ax.text(0.075, by, "✓", fontsize=8.5, color=SUCCESS, fontweight="bold")
            ax.text(0.100, by, bullet_text, fontsize=8.2, color=INK, va="center")

        # Where (code path)
        ax.text(0.93, y + 0.010, req["where"],
                fontsize=7.2, color=MUTED, ha="right", style="italic", family="monospace")

    page_footer(ax, 5)


def main():
    out = Path(__file__).parent.parent / "docs" / "architecture.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)

    pages = [page_1, page_2, page_3, page_4, page_5]
    with PdfPages(out) as pdf:
        for fn in pages:
            fig = plt.figure(figsize=(8.5, 11))
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            fn(ax)
            pdf.savefig(fig, dpi=200)
            plt.close(fig)

    size_kb = out.stat().st_size / 1024
    print(f"Wrote {out}  ({size_kb:.1f} KB, {len(pages)} pages)")


if __name__ == "__main__":
    main()

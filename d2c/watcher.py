"""Watcher loop: spawn `claude -p` with our MCP, capture cited proposal, validate, file to inbox.

Bet 1 verified in autonomous mode: the same MCP tools the interactive Claude Code
session uses get exercised by a headless `claude -p` invocation, which runs
without a human in the loop. The output is then validated against the canonical
envelopes table — every numeric claim must be bound to an envelope_id that
actually exists. Validation result is captured in the sidecar JSON next to
the markdown proposal.
"""

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from d2c.storage import db

PROMPT = """You are the autonomous watcher agent for merchant '{merchant_id}'.

Job: find the SINGLE highest-impact issue in this merchant's data right now and draft
a flagging proposal for the founder.

You have eight cognitive tools available via MCP. Don't call all of them — pick
THREE TO FIVE that seem most likely to reveal a high-impact, actionable signal
based on what a D2C founder would care about right now:

  • find_largest_discount_order(merchant_id, window_days)
       — biggest promotional/discount leakage.
  • find_reconciliation_gap_orders(merchant_id, window_days, min_gap_amount, limit)
       — orders where Razorpay settled materially less than Shopify net.
  • find_engaged_non_buyers(merchant_id, window_days, min_engagements, limit)
       — customers opening/clicking emails but not converting (warm-not-buying).
  • find_lapsed_high_value_customers(merchant_id, lapsed_days, min_lifetime_value, limit)
       — VIPs who've gone quiet (win-back targets).
  • find_top_customers_by_ltv(merchant_id, limit)
       — VIP roster (useful as context, rarely the proposal target itself).
  • compute_repeat_purchase_health(merchant_id, cohort_days)
       — recent-cohort vs prior-cohort repeat-purchase trend.
  • find_high_aov_outliers(merchant_id, window_days, aov_multiplier, limit)
       — orders unusually large vs the merchant mean (VIP or fraud).
  • get_customer_journey(merchant_id, email)
       — multi-source timeline for one specific person (drill-down).

Process:
1. Pick 3-5 tools you think will reveal the most actionable standout.
2. Call them with merchant_id='{merchant_id}' and sensible defaults.
3. Compare results by impact: prefer signals with concrete currency-value, then
   behavioral significance (e.g., declining repeat rate is high impact even
   without a single ₹ amount), then urgency.
4. Empty results are a clean signal, not a failure — skip those.
5. Pick the SINGLE most-actionable standout and draft the proposal.

PROPOSAL FORMAT — output exactly this, nothing else:

# Proposal: <one-line title naming the specific issue>

**Category:** <discount_review | reconciliation_review | retention_outreach | win_back | vip_attention | aov_investigation | cohort_health>
**Severity:** <low | medium | high>
**Estimated impact:** <amount, count, or qualitative measure> [cite:<envelope_id>]

## What I found

<2-3 sentences. Every number cited with [cite:<envelope_id>] within ~40 chars after the number. envelope_id must come from a tool result's citations array.>

## Evidence

- <bullet with [cite:<envelope_id>]>
- <bullet with [cite:<envelope_id>]>

## Recommended action

<1-2 concrete sentences. No new numbers; pass through tool-provided figures with their cites.>

## Why I picked this signal

<one or two short lines comparing the chosen signal to the others you considered. Name the alternatives by category.>

CRITICAL RULES (output is rejected if violated):
- Every numeric claim has [cite:<envelope_id>] within 80 chars after the number.
- Use ONLY envelope IDs from tool results — never invent IDs.
- Do not compute new numbers in prose. Pass through tool-provided figures with their cites.
- Output ONLY the proposal markdown. No preamble. No "let me look at this..." No closing remarks. Just the proposal."""


_CITE_RE = re.compile(r"\[cite:([a-fA-F0-9-]{8,})\]")
# Presence-only pattern for per-claim nearby-cite check. The full cite token
# can be up to ~44 chars; if we tried to match the closing `]` inside a small
# window, we'd false-fail when the cite starts near the window boundary.
_CITE_START_RE = re.compile(r"\[cite:[a-fA-F0-9-]")

# Magnitude regex — only flag numbers that look like quantitative claims
# about the data (money, percentages, large numbers). Skips day counts,
# date components, order numbers (which carry their own # prefix), etc.
_MAGNITUDE_RE = re.compile(
    r"""
    (?<![\/\#\-_a-zA-Z])                                  # not preceded by URL/ID chars
    (?:
        (?:[₹$€£]\s?\d{1,3}(?:[,_]\d{3})*(?:\.\d+)?)      # ₹X, $X
        |
        (?:(?:USD|INR|GBP|EUR)\s+\d{2,}(?:[,_]\d{3})*(?:\.\d+)?)  # USD 1234.56
        |
        (?:\d+(?:\.\d+)?%)                                # X% or X.X%
        |
        (?:\d{1,3}(?:[,_]\d{3})+(?:\.\d+)?)               # has thousand separator (1,234.56)
        |
        (?:\d{5,}(?:\.\d+)?)                              # plain 5+ digit (12345, 100000)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_YEAR_RE = re.compile(r"^\d{4}$")


def _is_year(claim: str) -> bool:
    if not _YEAR_RE.match(claim):
        return False
    n = int(claim)
    return 1900 <= n <= 2099


def _is_in_heading(text: str, pos: int) -> bool:
    """Numbers in markdown headings are titles — they don't need citations
    (the body restates them with cites)."""
    line_start = text.rfind("\n", 0, pos) + 1
    return text[line_start:pos].lstrip().startswith("#")


def _is_inside_cite_token(text: str, pos: int) -> bool:
    """True if pos is inside a [cite:...] token. Hex/digit fragments of an
    envelope_id aren't claims — they're part of the citation itself."""
    last_open = text.rfind("[cite:", 0, pos)
    if last_open == -1:
        return False
    close_between = text.find("]", last_open, pos)
    return close_between == -1


def _is_order_number_label(text: str, pos: int) -> bool:
    """True if the digits are immediately preceded by 'order'/'orders'/'#' —
    identifiers, not magnitude claims (citing #1009 as a number would be silly;
    the order's value is what gets cited)."""
    prefix = text[max(0, pos - 20):pos]
    return bool(re.search(r"(?:^|[^a-zA-Z])(?:orders?|#)\s*$", prefix, re.IGNORECASE))


def run_watcher(
    merchant_id: str,
    merchant_dir: Path,
    db_path: Path,
    project_root: Path,
    timeout_seconds: int = 300,
) -> dict:
    if not shutil.which("claude"):
        return {"status": "error", "error": "`claude` not on PATH; install Claude Code first"}

    started_at = datetime.now(timezone.utc)
    prompt = PROMPT.format(merchant_id=merchant_id)

    # --dangerously-skip-permissions: our MCP tools are read-only; we trust this
    # bounded local invocation. Tighter alternative is --allowed-tools with the
    # MCP tool list enumerated, which we'll switch to once names stabilize.
    cmd = [
        "claude",
        "-p", prompt,
        "--dangerously-skip-permissions",
        "--output-format", "json",
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "duration_seconds": timeout_seconds}

    if proc.returncode != 0:
        return {
            "status": "error",
            "exit_code": proc.returncode,
            "stderr": proc.stderr[-1000:],
            "stdout": proc.stdout[-500:],
        }

    # claude -p --output-format json returns {result, num_turns, duration_ms, ...}
    prose: str
    metadata: dict = {}
    try:
        parsed = json.loads(proc.stdout)
        prose = parsed.get("result", "") or ""
        metadata = {
            "num_turns": parsed.get("num_turns"),
            "duration_ms": parsed.get("duration_ms"),
            "total_cost_usd": parsed.get("total_cost_usd"),
            "session_id": parsed.get("session_id"),
        }
    except json.JSONDecodeError:
        prose = proc.stdout

    prose = _strip_preamble(prose)
    validation = _validate(prose, db_path)

    inbox_dir = merchant_dir / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    proposal_id = str(uuid4())
    ts = started_at.strftime("%Y%m%dT%H%M%SZ")
    md_path = inbox_dir / f"{ts}-{proposal_id[:8]}.md"
    json_path = inbox_dir / f"{ts}-{proposal_id[:8]}.json"

    md_path.write_text(prose if prose.strip() else "# (empty proposal — watcher returned no text)\n")
    sidecar = {
        "proposal_id": proposal_id,
        "merchant_id": merchant_id,
        "generated_at": started_at.isoformat(),
        "status": "pending",
        "category": _extract_field(prose, "Category"),
        "severity": _extract_field(prose, "Severity"),
        "validation": validation,
        "claude_run": metadata,
    }
    json_path.write_text(json.dumps(sidecar, indent=2))

    return {
        "status": "ok",
        "proposal_path": str(md_path),
        "sidecar_path": str(json_path),
        "validation": validation,
        "metadata": metadata,
    }


def _strip_preamble(prose: str) -> str:
    """Drop anything before the first '# Proposal:' heading."""
    m = re.search(r"^# Proposal:", prose, re.MULTILINE)
    return prose[m.start():] if m else prose


def _extract_field(prose: str, field: str) -> str | None:
    """Pull a value out of a `**Field:** value` line."""
    m = re.search(rf"\*\*{re.escape(field)}:\*\*\s*(.+)$", prose, re.MULTILINE)
    return m.group(1).strip() if m else None


def _validate(response: str, db_path: Path) -> dict:
    """Verify every [cite:UUID] resolves to a real envelope_id and every
    numeric claim has a citation within 80 chars after it."""
    conn = db.connect(db_path)

    cites = set(_CITE_RE.findall(response))
    if cites:
        placeholders = ",".join("?" * len(cites))
        rows = conn.execute(
            f"SELECT envelope_id FROM envelopes WHERE envelope_id IN ({placeholders})",
            list(cites),
        ).fetchall()
        existing = {r["envelope_id"] for r in rows}
    else:
        existing = set()
    unknown = sorted(cites - existing)

    unbound: list[str] = []
    for m in _MAGNITUDE_RE.finditer(response):
        claim = m.group(0).strip()
        if not claim:
            continue
        if _is_year(claim):
            continue
        if _is_in_heading(response, m.start()):
            continue
        if _is_inside_cite_token(response, m.start()):
            continue
        if _is_order_number_label(response, m.start()):
            continue
        window = response[m.end():m.end() + 80]
        if not _CITE_START_RE.search(window):
            unbound.append(claim)

    return {
        "is_valid": (not unknown and not unbound),
        "unknown_cite_envelope_ids": unknown,
        "uncited_numeric_claims": unbound[:20],
        "total_cites": len(cites),
        "resolved_cites": len(existing),
    }

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import click

from d2c.config import MerchantConfig
from d2c.storage import db
from d2c.sync import sync_one

PROJECT_ROOT = Path(__file__).parent.parent.parent
MERCHANTS_DIR = PROJECT_ROOT / "merchants"


_BANNER = r"""
  ____  _   _ ___ _     ____  _____ ____
 | __ )| | | |_ _| |   |  _ \| ____|  _ \
 |  _ \| | | || || |   | | | |  _| | |_) |
 | |_) | |_| || || |___| |_| | |___|  _ <
 |____/ \___/|___|_____|____/|_____|_| \_\
"""


def _print_banner(subtitle: str | None = None) -> None:
    """Print the BUILDER ASCII banner with an optional subtitle line.

    Used at the top of `d2c init` to give the interactive setup a
    distinct, recognizable opening — useful for demo videos and for
    making the install flow feel polished."""
    click.secho(_BANNER, fg="cyan", bold=True)
    if subtitle:
        click.secho(f"   {subtitle}", fg="bright_black")
        click.secho("   " + "─" * (len(subtitle) + 2), fg="bright_black")
    click.echo()


def _ok(text: str) -> None:
    """Print a green check + text — for successful writes/steps."""
    click.echo(f"  {click.style('✓', fg='green', bold=True)} {text}")


def _section(title: str) -> None:
    """Print a colored section header with the cyan accent."""
    click.echo()
    click.secho(f"─── {title} ───", fg="cyan", bold=True)


def _hint(text: str) -> None:
    """Print a dim instructional line below a section header."""
    click.secho(f"    {text}", fg="bright_black")


def _load_merchant(merchant_id: str) -> MerchantConfig:
    merchant_dir = MERCHANTS_DIR / merchant_id
    if not merchant_dir.is_dir():
        raise click.UsageError(f"Merchant directory not found: {merchant_dir}")
    return MerchantConfig.load(merchant_dir)


def _db_path(merchant_id: str) -> Path:
    return PROJECT_ROOT / "data" / merchant_id / "canonical.db"


def _raw_lake_dir() -> Path:
    return PROJECT_ROOT / "data" / "raw_lake"


@click.group()
def cli() -> None:
    """D2C AI Employee — operator CLI."""


@cli.command()
@click.argument("merchant_id")
@click.option(
    "--overwrite",
    is_flag=True,
    help="Replace existing merchant directory if present.",
)
def init(merchant_id: str, overwrite: bool) -> None:
    """Interactive setup for a new merchant. Writes config.yaml + .env + CLAUDE.md.

    Run this once per merchant you want to operate on. It prompts for the
    credentials it needs and writes them to a gitignored `.env`.
    """
    merchant_dir = MERCHANTS_DIR / merchant_id
    if merchant_dir.exists() and any(merchant_dir.iterdir()) and not overwrite:
        raise click.UsageError(
            f"{merchant_dir} already exists and is not empty. "
            f"Pass --overwrite to replace, or use a different merchant id."
        )
    merchant_dir.mkdir(parents=True, exist_ok=True)

    _print_banner(f"initializing merchant '{merchant_id}'")

    _section("Shopify  (custom app admin token)")
    _hint("Dev store admin → Settings → Apps and sales channels →")
    _hint("Develop apps → your app → API credentials → Reveal token once.")
    shop_domain = click.prompt(
        "    Shop domain (e.g., my-store.myshopify.com)",
        type=str,
    )
    shopify_token = click.prompt(
        "    Admin API access token (shpat_...)",
        hide_input=True,
        type=str,
    )
    shopify_key = click.prompt(
        "    API key (32-char hex; press Enter to skip)",
        hide_input=True,
        default="",
        show_default=False,
        type=str,
    )
    shopify_secret = click.prompt(
        "    API secret key (32-char hex; press Enter to skip)",
        hide_input=True,
        default="",
        show_default=False,
        type=str,
    )

    _section("Klaviyo  (private API key)")
    klaviyo_enabled = click.confirm("    Configure Klaviyo?", default=True)
    klaviyo_key = ""
    if klaviyo_enabled:
        _hint("Klaviyo → Account → Settings → API Keys → Create Private API Key.")
        klaviyo_key = click.prompt(
            "    Private API key (pk_...)", hide_input=True, type=str
        )

    _section("Razorpay  (test mode)")
    razorpay_enabled = click.confirm("    Configure Razorpay?", default=True)
    razorpay_key_id = ""
    razorpay_secret = ""
    if razorpay_enabled:
        _hint("Razorpay Dashboard (test mode) → Settings → API Keys.")
        razorpay_key_id = click.prompt(
            "    Key ID (rzp_test_...)", hide_input=True, type=str
        )
        razorpay_secret = click.prompt(
            "    Key Secret", hide_input=True, type=str
        )

    config_yaml = f"""# D2C AI Employee — non-secret per-merchant config for "{merchant_id}"
# Secrets live in .env (gitignored) alongside this file.

merchant_id: {merchant_id}
merchant_name: "{merchant_id.replace('-', ' ').replace('_', ' ').title()}"
timezone: "Asia/Kolkata"
base_currency: "INR"

connectors:
  shopify:
    enabled: true
    shop_domain: "{shop_domain}"
    api_version: "2024-10"
    scopes:
      - read_orders
      - read_products
      - read_customers
      - read_fulfillments
      - read_inventory
      - read_discounts

  klaviyo:
    enabled: {str(klaviyo_enabled).lower()}
    api_revision: "2024-10-15"

  razorpay:
    enabled: {str(razorpay_enabled).lower()}
    mode: test

ingestion:
  # v0 uses polling instead of webhooks — no public tunnel needed.
  mode: polling
  poll_intervals_minutes:
    shopify: 15
    klaviyo: 30
    razorpay: 30
  watcher_cron: "0 6 * * *"

raw_lake:
  path: "./data/raw_lake"
  partition_by: ["source", "date"]
"""

    env_content = f"""# D2C AI Employee — merchant credentials for "{merchant_id}"
# This file is gitignored. Never commit. Never paste contents into chat.

SHOPIFY_ADMIN_API_TOKEN={shopify_token}
SHOPIFY_API_KEY={shopify_key}
SHOPIFY_API_SECRET={shopify_secret}
SHOPIFY_WEBHOOK_SECRET=

KLAVIYO_PRIVATE_API_KEY={klaviyo_key}

RAZORPAY_KEY_ID={razorpay_key_id}
RAZORPAY_KEY_SECRET={razorpay_secret}

# Optional — only set if running loops outside Claude Code (e.g., cloud cron).
# ANTHROPIC_API_KEY=
"""

    claude_md = f"""# Merchant context: {merchant_id}

This file is loaded by every loop invocation against this merchant. Plain text,
version-controlled (per your own repo), editable by the founder.

## Vocabulary

(Merchant-specific — cohort names, SKU shorthand, internal terms.)

- (none yet)

## Standing orders

(Things the agent must respect across all loops for this merchant.)

- (none yet)

## Pinned investigations

(Questions the founder asks often — muscle memory for the agent.)

- (none yet)

## Notes from prior investigations

(Things the founder has written back — what's been tried, what didn't work, why.)

- (none yet)

## Trust state

Current autonomy rungs per action category live in the reflective layer of
the MCP (`trust_state` table). For v0 all categories start at rung 1 (Observe).
"""

    (merchant_dir / "config.yaml").write_text(config_yaml)
    (merchant_dir / ".env").write_text(env_content)
    (merchant_dir / "CLAUDE.md").write_text(claude_md)

    click.echo()
    _ok(f"wrote {merchant_dir}/config.yaml")
    _ok(f"wrote {merchant_dir}/.env           {click.style('(gitignored)', fg='bright_black')}")
    _ok(f"wrote {merchant_dir}/CLAUDE.md")

    click.echo()
    click.secho("Next steps:", fg="cyan", bold=True)
    arrow = click.style("▸", fg="cyan")
    click.echo(
        f"  {arrow} uv run d2c verify {merchant_id}                    "
        f"{click.style('# test API access', fg='bright_black')}"
    )
    click.echo(
        f"  {arrow} uv run d2c sync {merchant_id} --source shopify     "
        f"{click.style('# pull existing data', fg='bright_black')}"
    )
    click.echo(
        f"  {arrow} uv run d2c project {merchant_id} --source shopify  "
        f"{click.style('# envelopes -> canonical', fg='bright_black')}"
    )
    click.echo()


@cli.command()
@click.argument("merchant_id")
def verify(merchant_id: str) -> None:
    """Test-ping each enabled source to confirm credentials and connectivity.

    Run this right after `d2c init` to surface auth issues before you sync
    real data. Each source either prints OK with a short identity line, or
    FAIL with the error class.
    """
    import httpx

    config = _load_merchant(merchant_id)
    click.echo(f"Verifying credentials for '{merchant_id}'...")

    # Shopify
    shopify_cfg = config.connectors.get("shopify") or {}
    if shopify_cfg.get("enabled"):
        try:
            domain = shopify_cfg["shop_domain"]
            api_version = shopify_cfg.get("api_version", "2024-10")
            token = config.secret("SHOPIFY_ADMIN_API_TOKEN")
            with httpx.Client(timeout=15) as c:
                r = c.get(
                    f"https://{domain}/admin/api/{api_version}/shop.json",
                    headers={"X-Shopify-Access-Token": token},
                )
            if r.status_code == 200:
                shop = r.json()["shop"]
                click.echo(f"  shopify   OK    {shop['name']} ({shop['domain']})")
            else:
                click.echo(f"  shopify   FAIL  HTTP {r.status_code}")
        except KeyError as e:
            click.echo(f"  shopify   FAIL  missing credential: {e}")
        except Exception as e:
            click.echo(f"  shopify   FAIL  {type(e).__name__}: {e}")
    else:
        click.echo("  shopify   skip  (disabled in config)")

    # Klaviyo
    klaviyo_cfg = config.connectors.get("klaviyo") or {}
    if klaviyo_cfg.get("enabled"):
        try:
            key = config.secret("KLAVIYO_PRIVATE_API_KEY")
            rev = klaviyo_cfg.get("api_revision", "2024-10-15")
            with httpx.Client(timeout=15) as c:
                r = c.get(
                    "https://a.klaviyo.com/api/accounts",
                    headers={
                        "Authorization": f"Klaviyo-API-Key {key}",
                        "revision": rev,
                        "accept": "application/json",
                    },
                )
            if r.status_code == 200:
                accounts = r.json().get("data") or []
                org = (
                    accounts[0]["attributes"]
                    .get("contact_information", {})
                    .get("organization_name", "account")
                    if accounts
                    else "account"
                )
                click.echo(f"  klaviyo   OK    {org}")
            else:
                click.echo(f"  klaviyo   FAIL  HTTP {r.status_code}")
        except KeyError as e:
            click.echo(f"  klaviyo   FAIL  missing credential: {e}")
        except Exception as e:
            click.echo(f"  klaviyo   FAIL  {type(e).__name__}: {e}")
    else:
        click.echo("  klaviyo   skip  (disabled in config)")

    # Razorpay
    razorpay_cfg = config.connectors.get("razorpay") or {}
    if razorpay_cfg.get("enabled"):
        try:
            key_id = config.secret("RAZORPAY_KEY_ID")
            secret = config.secret("RAZORPAY_KEY_SECRET")
            with httpx.Client(timeout=15) as c:
                r = c.get(
                    "https://api.razorpay.com/v1/orders?count=1",
                    auth=(key_id, secret),
                )
            if r.status_code == 200:
                mode = "test" if key_id.startswith("rzp_test_") else "live"
                click.echo(f"  razorpay  OK    {mode} mode")
            else:
                click.echo(f"  razorpay  FAIL  HTTP {r.status_code}")
        except KeyError as e:
            click.echo(f"  razorpay  FAIL  missing credential: {e}")
        except Exception as e:
            click.echo(f"  razorpay  FAIL  {type(e).__name__}: {e}")
    else:
        click.echo("  razorpay  skip  (disabled in config)")

    click.echo()
    click.echo(f"If all OK, run: uv run d2c sync {merchant_id} --source shopify")


@cli.command()
@click.argument("merchant_id")
@click.option(
    "--source",
    type=click.Choice(["shopify", "razorpay", "klaviyo"]),
    required=True,
    help="Which source to sync.",
)
def sync(merchant_id: str, source: str) -> None:
    """Pull a source for a merchant and land envelopes in the raw lake."""
    config = _load_merchant(merchant_id)
    conn = db.connect(_db_path(merchant_id))
    db.bootstrap(conn)

    click.echo(f"Syncing {source} for merchant '{merchant_id}'...")
    result = sync_one(config, source, _raw_lake_dir(), conn)
    if "skipped" not in result and result.get("skipped") is True:
        click.echo(f"  {source} disabled in config, skipping.")
        return
    new_counts = result.get("new", {})
    skipped_counts = result.get("skipped", {})
    if not new_counts and not skipped_counts:
        click.echo("  no records returned (cursor caught up or empty source).")
        return
    object_types = sorted(set(new_counts.keys()) | set(skipped_counts.keys()))
    for object_type in object_types:
        n = new_counts.get(object_type, 0)
        s = skipped_counts.get(object_type, 0)
        click.echo(f"  {object_type:15} {n:>4} new, {s:>4} duplicate (skipped)")
    click.echo("Done.")


@cli.command()
@click.argument("merchant_id")
def status(merchant_id: str) -> None:
    """Show envelope counts per (source, object_type) for a merchant."""
    conn = db.connect(_db_path(merchant_id))
    db.bootstrap(conn)
    rows = conn.execute(
        """
        SELECT source, source_object_type, COUNT(*) AS n,
               MAX(fetched_at) AS last_fetched
          FROM envelopes
         WHERE merchant_id = ?
         GROUP BY source, source_object_type
         ORDER BY source, source_object_type
        """,
        (merchant_id,),
    ).fetchall()
    if not rows:
        click.echo(
            f"No envelopes yet for '{merchant_id}'. "
            f"Run `d2c sync {merchant_id} --source shopify` first."
        )
        return
    click.echo(f"Envelope counts for merchant '{merchant_id}':")
    for r in rows:
        click.echo(
            f"  {r['source']:10} {r['source_object_type']:15} "
            f"{r['n']:>6}  (last fetched {r['last_fetched']})"
        )


@cli.command()
@click.argument("merchant_id")
@click.option(
    "--source",
    type=click.Choice(["shopify", "razorpay", "klaviyo"]),
    required=True,
    help="Which source to project.",
)
def project(merchant_id: str, source: str) -> None:
    """Project envelopes into canonical entity rows for the given merchant."""
    _load_merchant(merchant_id)  # validates the merchant exists
    conn = db.connect(_db_path(merchant_id))
    db.bootstrap(conn)
    click.echo(f"Projecting {source} for merchant '{merchant_id}'...")
    if source == "shopify":
        from d2c.projections.shopify import project_all
        counts = project_all(conn, merchant_id)
    elif source == "razorpay":
        from d2c.projections.razorpay import project_all
        counts = project_all(conn, merchant_id)
    elif source == "klaviyo":
        from d2c.projections.klaviyo import project_all
        counts = project_all(conn, merchant_id)
    else:
        raise click.UsageError(f"No projection for source {source!r}")
    for entity, count in counts.items():
        click.echo(f"  {entity:15} {count:>6} rows projected")
    click.echo("Done.")


@cli.command()
@click.argument("merchant_id")
@click.option(
    "--source",
    type=click.Choice(["shopify", "razorpay", "klaviyo"]),
    required=True,
    help="Which source to seed.",
)
@click.option(
    "--count",
    default=50,
    show_default=True,
    help="Number of orders to seed (shopify only; razorpay seeds from existing Shopify orders).",
)
def seed(merchant_id: str, source: str, count: int) -> None:
    """Seed sample data for the given merchant and source."""
    config = _load_merchant(merchant_id)
    conn = db.connect(_db_path(merchant_id))
    db.bootstrap(conn)

    if source == "shopify":
        from d2c.seeder.shopify_orders import ShopifyOrderSeeder
        seeder = ShopifyOrderSeeder(config)
        try:
            click.echo(f"Seeding {count} orders into Shopify for '{merchant_id}'...")
            results = seeder.seed(count)
        finally:
            seeder.close()
        click.echo(f"  created: {results['created']}, errors: {results['errors']}")
        click.echo("Done. Run `d2c sync default --source shopify` to land them.")
    elif source == "razorpay":
        from d2c.seeder.razorpay_orders import RazorpayOrderSeeder
        seeder = RazorpayOrderSeeder(config, conn)
        try:
            click.echo(
                f"Seeding Razorpay orders for '{merchant_id}' "
                f"(one per canonical Shopify order, ~15% with synthetic gap)..."
            )
            results = seeder.seed_from_shopify()
        finally:
            seeder.close()
        click.echo(
            f"  created: {results['created']}, skipped: {results['skipped']}, "
            f"errors: {results['errors']}, with_gap: {results['with_gap']}"
        )
        click.echo("Done. Run `d2c sync default --source razorpay` to land them.")
    elif source == "klaviyo":
        from d2c.seeder.klaviyo_events import KlaviyoSeeder
        seeder = KlaviyoSeeder(config, conn)
        try:
            click.echo(
                f"Seeding Klaviyo profiles + email events for '{merchant_id}' "
                f"(matched to existing Shopify customers by email)..."
            )
            results = seeder.seed_from_shopify()
        finally:
            seeder.close()
        click.echo(
            f"  profiles: {results['profiles']}, events: {results['events']}, "
            f"errors: {results['errors']}"
        )
        click.echo("Done. Run `d2c sync default --source klaviyo` to land them.")
    else:
        raise click.UsageError(f"No seeder for source {source!r}")


@cli.command()
@click.argument("merchant_id")
@click.option("--timeout", default=300, show_default=True, help="Watcher timeout (seconds).")
def watch(merchant_id: str, timeout: int) -> None:
    """Run the autonomous watcher. Spawns `claude -p` with the MCP server."""
    from d2c import watcher
    _load_merchant(merchant_id)
    merchant_dir = MERCHANTS_DIR / merchant_id

    click.echo(f"Watcher running for '{merchant_id}'... (may take 30-90s)")
    result = watcher.run_watcher(
        merchant_id=merchant_id,
        merchant_dir=merchant_dir,
        db_path=_db_path(merchant_id),
        project_root=PROJECT_ROOT,
        timeout_seconds=timeout,
    )

    if result["status"] == "ok":
        v = result["validation"]
        click.echo(f"  proposal: {result['proposal_path']}")
        click.echo(f"  sidecar:  {result['sidecar_path']}")
        verdict = "PASS" if v["is_valid"] else "FAIL"
        click.echo(
            f"  validation: {verdict}  "
            f"(cites: {v['resolved_cites']}/{v['total_cites']} resolve)"
        )
        if not v["is_valid"]:
            if v["unknown_cite_envelope_ids"]:
                click.echo(
                    f"    unknown envelope_ids in cites: "
                    f"{v['unknown_cite_envelope_ids'][:3]}"
                )
            if v["uncited_numeric_claims"]:
                click.echo(
                    f"    uncited numeric claims: "
                    f"{v['uncited_numeric_claims'][:5]}"
                )
        meta = result.get("metadata") or {}
        if meta.get("duration_ms"):
            click.echo(
                f"  claude run: {meta['num_turns']} turns, "
                f"{meta['duration_ms']/1000:.1f}s, "
                f"${meta.get('total_cost_usd', 0):.4f}"
            )
    else:
        click.echo(f"  status: {result['status']}")
        for k, val in result.items():
            if k != "status":
                click.echo(f"  {k}: {str(val)[:400]}")


@cli.command()
@click.argument("merchant_id")
def inbox(merchant_id: str) -> None:
    """List pending watcher proposals for the merchant."""
    inbox_dir = MERCHANTS_DIR / merchant_id / "inbox"
    if not inbox_dir.exists():
        click.echo(f"No inbox yet for '{merchant_id}'. Run `d2c watch {merchant_id}` first.")
        return

    sidecars = sorted(inbox_dir.glob("*.json"))
    pending = []
    decided = []
    for s in sidecars:
        try:
            data = json.loads(s.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("status") == "pending":
            pending.append((s, data))
        else:
            decided.append((s, data))

    if not pending and not decided:
        click.echo(f"No proposals in inbox for '{merchant_id}'.")
        return

    if pending:
        click.echo(f"Pending proposals ({len(pending)}):")
        for sidecar, data in pending:
            md = sidecar.with_suffix(".md")
            v = data.get("validation", {})
            verdict = "PASS" if v.get("is_valid") else "FAIL"
            click.echo(
                f"  {md.name}  "
                f"[{data.get('category') or '?'}/{data.get('severity') or '?'}]  "
                f"validation: {verdict}"
            )
    if decided:
        click.echo(f"\nDecided proposals ({len(decided)}):")
        for sidecar, data in decided[-10:]:
            md = sidecar.with_suffix(".md")
            click.echo(
                f"  {md.name}  outcome={data.get('status')}  "
                f"decided_at={data.get('decided_at', '?')[:19]}"
            )


@cli.command()
@click.argument("merchant_id")
@click.argument("proposal_name")
@click.argument("outcome", type=click.Choice(["approved", "rejected", "modified"]))
@click.option("--reason", default="", help="Reason for the decision.")
def decide(merchant_id: str, proposal_name: str, outcome: str, reason: str) -> None:
    """Record an approve/reject/modify decision on a watcher proposal.

    PROPOSAL_NAME is the inbox filename (md or json prefix).
    """
    inbox_dir = MERCHANTS_DIR / merchant_id / "inbox"
    base = proposal_name.removesuffix(".md").removesuffix(".json")
    json_path = inbox_dir / f"{base}.json"
    if not json_path.exists():
        raise click.UsageError(f"Proposal sidecar not found: {json_path}")

    data = json.loads(json_path.read_text())
    decided_at = datetime.now(timezone.utc).isoformat()
    data["status"] = outcome
    data["decided_at"] = decided_at
    data["decision_reason"] = reason
    json_path.write_text(json.dumps(data, indent=2))

    conn = db.connect(_db_path(merchant_id))
    db.bootstrap(conn)
    category = data.get("category") or "uncategorized"
    conn.execute(
        """
        INSERT INTO decisions (
            decision_id, merchant_id, proposal_id, proposal_category,
            decided_at, decided_by, outcome, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            merchant_id,
            data["proposal_id"],
            category,
            decided_at,
            "founder",
            outcome,
            reason,
        ),
    )
    conn.commit()
    click.echo(f"Decision recorded: {outcome}")
    click.echo(f"  proposal_id: {data['proposal_id']}")
    click.echo(f"  category: {category}")
    if reason:
        click.echo(f"  reason: {reason}")


@cli.command()
@click.argument("merchant_id")
@click.confirmation_option(
    prompt="Delete local canonical DB and raw lake for this merchant? (source APIs are not touched)"
)
def reset(merchant_id: str) -> None:
    """Delete local data for a merchant (canonical DB + raw lake JSONL + inbox).

    Source APIs (Shopify/Razorpay/Klaviyo) are NOT touched. Useful for clean
    re-sync after schema or envelope-id algorithm changes.
    """
    import shutil

    paths = [
        PROJECT_ROOT / "data" / merchant_id,
        PROJECT_ROOT / "data" / "raw_lake" / merchant_id,
        MERCHANTS_DIR / merchant_id / "inbox",
    ]
    for p in paths:
        if p.exists():
            shutil.rmtree(p)
            click.echo(f"  removed {p}")
        else:
            click.echo(f"  not present {p}")
    click.echo("Done. Re-run sync + project for each source.")


if __name__ == "__main__":
    cli()

-- D2C AI Employee — canonical store schema (SQLite)
-- Multi-tenant from day one: every row carries merchant_id.

-- =====================================================================
-- Raw lake landing index
-- =====================================================================
-- Append-only. Never mutated. The replay tape.
-- Disk holds the bytes (JSONL); this table indexes them for fast lookup.
CREATE TABLE IF NOT EXISTS envelopes (
    envelope_id          TEXT PRIMARY KEY,
    merchant_id          TEXT NOT NULL,
    source               TEXT NOT NULL,
    source_version       TEXT NOT NULL,
    connector_version    TEXT NOT NULL,
    source_object_type   TEXT NOT NULL,
    source_object_id     TEXT NOT NULL,
    source_event_type    TEXT,
    fetched_at           TEXT NOT NULL,
    source_updated_at    TEXT,
    payload_json         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_envelopes_lookup
    ON envelopes (merchant_id, source, source_object_type, source_object_id);
CREATE INDEX IF NOT EXISTS idx_envelopes_fetched
    ON envelopes (merchant_id, fetched_at);

-- =====================================================================
-- Sync cursors (polling high-water-marks)
-- =====================================================================
CREATE TABLE IF NOT EXISTS sync_cursors (
    merchant_id     TEXT NOT NULL,
    source          TEXT NOT NULL,
    object_type     TEXT NOT NULL,
    cursor_value    TEXT,
    last_sync_at    TEXT NOT NULL,
    PRIMARY KEY (merchant_id, source, object_type)
);

-- =====================================================================
-- Canonical entities
-- =====================================================================
-- Each derived row carries:
--   - derived_from_envelope_id → source envelope (provenance)
--   - projection_version → which projection produced it (lazy re-projection)

CREATE TABLE IF NOT EXISTS customers (
    canonical_id              TEXT NOT NULL,
    merchant_id               TEXT NOT NULL,
    derived_from_envelope_id  TEXT NOT NULL,
    projection_version        TEXT NOT NULL,
    aliases_json              TEXT NOT NULL,
    email                     TEXT,
    phone                     TEXT,
    first_seen_at             TEXT,
    PRIMARY KEY (canonical_id, projection_version),
    FOREIGN KEY (derived_from_envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE INDEX IF NOT EXISTS idx_customers_merchant ON customers (merchant_id);
CREATE INDEX IF NOT EXISTS idx_customers_email ON customers (merchant_id, email);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers (merchant_id, phone);

CREATE TABLE IF NOT EXISTS products (
    canonical_id              TEXT NOT NULL,
    merchant_id               TEXT NOT NULL,
    derived_from_envelope_id  TEXT NOT NULL,
    projection_version        TEXT NOT NULL,
    sku                       TEXT,
    title                     TEXT,
    attributes_json           TEXT,
    PRIMARY KEY (canonical_id, projection_version),
    FOREIGN KEY (derived_from_envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE INDEX IF NOT EXISTS idx_products_merchant ON products (merchant_id);
CREATE INDEX IF NOT EXISTS idx_products_sku ON products (merchant_id, sku);

CREATE TABLE IF NOT EXISTS orders (
    canonical_id              TEXT NOT NULL,
    merchant_id               TEXT NOT NULL,
    derived_from_envelope_id  TEXT NOT NULL,
    projection_version        TEXT NOT NULL,
    customer_canonical_id     TEXT,
    order_number              TEXT,
    placed_at                 TEXT NOT NULL,
    gross_revenue             REAL,
    total_discount            REAL DEFAULT 0,
    total_tax                 REAL DEFAULT 0,
    total_shipping            REAL DEFAULT 0,
    net_revenue               REAL,
    settled_revenue           REAL,
    currency                  TEXT,
    status                    TEXT,
    PRIMARY KEY (canonical_id, projection_version),
    FOREIGN KEY (derived_from_envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_merchant ON orders (merchant_id);
CREATE INDEX IF NOT EXISTS idx_orders_placed ON orders (merchant_id, placed_at);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders (merchant_id, customer_canonical_id);

CREATE TABLE IF NOT EXISTS order_lines (
    canonical_id              TEXT NOT NULL,
    merchant_id               TEXT NOT NULL,
    derived_from_envelope_id  TEXT NOT NULL,
    projection_version        TEXT NOT NULL,
    order_canonical_id        TEXT NOT NULL,
    product_canonical_id      TEXT,
    quantity                  INTEGER NOT NULL,
    unit_price                REAL,
    discount                  REAL DEFAULT 0,
    PRIMARY KEY (canonical_id, projection_version),
    FOREIGN KEY (derived_from_envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE INDEX IF NOT EXISTS idx_order_lines_order ON order_lines (order_canonical_id);

CREATE TABLE IF NOT EXISTS shipments (
    canonical_id              TEXT NOT NULL,
    merchant_id               TEXT NOT NULL,
    derived_from_envelope_id  TEXT NOT NULL,
    projection_version        TEXT NOT NULL,
    order_canonical_id        TEXT,
    status                    TEXT,
    tracking_number           TEXT,
    last_status_at            TEXT,
    PRIMARY KEY (canonical_id, projection_version),
    FOREIGN KEY (derived_from_envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE INDEX IF NOT EXISTS idx_shipments_merchant ON shipments (merchant_id);
CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments (order_canonical_id);

CREATE TABLE IF NOT EXISTS messages (
    canonical_id              TEXT NOT NULL,
    merchant_id               TEXT NOT NULL,
    derived_from_envelope_id  TEXT NOT NULL,
    projection_version        TEXT NOT NULL,
    customer_canonical_id     TEXT,
    channel                   TEXT,
    direction                 TEXT,
    state                     TEXT,
    sent_at                   TEXT,
    PRIMARY KEY (canonical_id, projection_version),
    FOREIGN KEY (derived_from_envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_merchant ON messages (merchant_id);
CREATE INDEX IF NOT EXISTS idx_messages_customer ON messages (merchant_id, customer_canonical_id);

CREATE TABLE IF NOT EXISTS events (
    canonical_id              TEXT NOT NULL,
    merchant_id               TEXT NOT NULL,
    derived_from_envelope_id  TEXT NOT NULL,
    projection_version        TEXT NOT NULL,
    event_type                TEXT NOT NULL,
    event_time                TEXT NOT NULL,
    entity_refs_json          TEXT NOT NULL,
    payload_json              TEXT,
    PRIMARY KEY (canonical_id, projection_version),
    FOREIGN KEY (derived_from_envelope_id) REFERENCES envelopes(envelope_id)
);
CREATE INDEX IF NOT EXISTS idx_events_merchant_time ON events (merchant_id, event_time);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (merchant_id, event_type, event_time);

-- =====================================================================
-- Identity resolution (deferred reconciliation pass)
-- =====================================================================
CREATE TABLE IF NOT EXISTS identity_merges (
    merge_id                  TEXT PRIMARY KEY,
    merchant_id               TEXT NOT NULL,
    primary_canonical_id      TEXT NOT NULL,
    merged_canonical_id       TEXT NOT NULL,
    confidence                REAL NOT NULL,
    matched_by                TEXT NOT NULL,
    merged_at                 TEXT NOT NULL,
    status                    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_id_merges_primary
    ON identity_merges (merchant_id, primary_canonical_id);

-- =====================================================================
-- Reflective layer
-- =====================================================================

-- Beliefs: structured epistemic state. Each row is a current belief.
-- Emitted by cognitive detectors (automatic thresholds) and watcher sessions.
-- Skeptic loop reads from here and attempts to falsify.
CREATE TABLE IF NOT EXISTS beliefs (
    belief_id                 TEXT PRIMARY KEY,
    merchant_id               TEXT NOT NULL,
    subject_kind              TEXT NOT NULL,
    subject_ref               TEXT NOT NULL,
    claim_type                TEXT NOT NULL,
    claim_payload_json        TEXT NOT NULL,
    confidence                REAL NOT NULL,
    formed_at                 TEXT NOT NULL,
    formed_by_loop            TEXT NOT NULL,
    formed_by_session         TEXT,
    model_version             TEXT,
    evidence_envelope_ids_json TEXT NOT NULL,
    falsification_conditions  TEXT NOT NULL,
    expires_at                TEXT,
    status                    TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_beliefs_active
    ON beliefs (merchant_id, status, claim_type);

-- Decision records: founder's structured action on proposals.
-- Inputs to the trust ratchet — ratchet reads from records, not inbox state.
CREATE TABLE IF NOT EXISTS decisions (
    decision_id               TEXT PRIMARY KEY,
    merchant_id               TEXT NOT NULL,
    proposal_id               TEXT NOT NULL,
    proposal_category         TEXT NOT NULL,
    decided_at                TEXT NOT NULL,
    decided_by                TEXT NOT NULL,
    outcome                   TEXT NOT NULL,
    reason                    TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_merchant
    ON decisions (merchant_id, decided_at);
CREATE INDEX IF NOT EXISTS idx_decisions_category
    ON decisions (merchant_id, proposal_category);

-- Trust state: per (merchant, category) autonomy rung + structural ceiling.
-- max_rung pins legal-shaped categories (pricing, refunds) at 4 forever.
CREATE TABLE IF NOT EXISTS trust_state (
    merchant_id                  TEXT NOT NULL,
    category                     TEXT NOT NULL,
    current_rung                 INTEGER NOT NULL,
    max_rung                     INTEGER NOT NULL,
    last_ratchet_at              TEXT,
    last_ratchet_model_version   TEXT,
    updated_at                   TEXT NOT NULL,
    PRIMARY KEY (merchant_id, category)
);

-- Changelog: what the system has done.
CREATE TABLE IF NOT EXISTS changelog (
    entry_id                  TEXT PRIMARY KEY,
    merchant_id               TEXT NOT NULL,
    occurred_at               TEXT NOT NULL,
    loop_name                 TEXT NOT NULL,
    session_id                TEXT,
    summary                   TEXT NOT NULL,
    details_json              TEXT
);
CREATE INDEX IF NOT EXISTS idx_changelog_merchant_time
    ON changelog (merchant_id, occurred_at);

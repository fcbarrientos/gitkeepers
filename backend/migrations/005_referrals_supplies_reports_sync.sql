CREATE TABLE referral_flags (
    id            TEXT PRIMARY KEY,
    visit_id      TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    rule_id       TEXT NOT NULL,
    reason_en     TEXT NOT NULL,
    reason_fil    TEXT NOT NULL,
    urgency       TEXT NOT NULL CHECK (urgency IN ('urgent', 'routine')),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'referred', 'dismissed')),
    dismiss_note  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_flags_status ON referral_flags(status, created_at);
CREATE INDEX idx_flags_patient ON referral_flags(patient_id);
CREATE INDEX idx_flags_visit ON referral_flags(visit_id);

CREATE TABLE referrals (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    flag_id     TEXT REFERENCES referral_flags(id),
    facility    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    urgency     TEXT NOT NULL CHECK (urgency IN ('urgent', 'routine')),
    notes       TEXT,
    status      TEXT NOT NULL DEFAULT 'issued' CHECK (status IN ('issued', 'sent')),
    created_by  TEXT NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_referrals_patient ON referrals(patient_id);

CREATE TABLE supply_items (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL UNIQUE COLLATE NOCASE,
    unit                 TEXT NOT NULL,
    low_stock_threshold  INTEGER NOT NULL CHECK (low_stock_threshold >= 0),
    target_level         INTEGER NOT NULL CHECK (target_level >= 0),
    active               INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE supply_movements (
    id             TEXT PRIMARY KEY,
    item_id        TEXT NOT NULL REFERENCES supply_items(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('received', 'distributed', 'adjusted')),
    quantity       INTEGER NOT NULL,   -- signed change in stock: received > 0, distributed < 0
    movement_date  TEXT NOT NULL,      -- YYYY-MM-DD
    note           TEXT,
    recorded_by    TEXT NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_movements_item ON supply_movements(item_id, movement_date);

CREATE TABLE report_drafts (
    id            TEXT PRIMARY KEY,
    period        TEXT NOT NULL CHECK (period IN ('week', 'month')),
    start_date    TEXT NOT NULL,
    end_date      TEXT NOT NULL,
    figures_json  TEXT NOT NULL,       -- the summary the draft was written from
    text          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
    model         TEXT,                -- NULL when written by hand
    created_by    TEXT NOT NULL REFERENCES users(id),
    approved_by   TEXT REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_drafts_period ON report_drafts(period, start_date);

CREATE TABLE sync_bundles (
    id               TEXT PRIMARY KEY,
    record_count     INTEGER NOT NULL,
    bundle_json      TEXT NOT NULL,    -- kept so the same file can be downloaded again
    created_by       TEXT NOT NULL REFERENCES users(id),
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    acknowledged_at  TEXT
);

CREATE TABLE sync_bundle_records (
    bundle_id          TEXT NOT NULL REFERENCES sync_bundles(id) ON DELETE CASCADE,
    record_type        TEXT NOT NULL,
    record_id          TEXT NOT NULL,
    record_updated_at  TEXT NOT NULL,  -- the version that was exported
    PRIMARY KEY (bundle_id, record_type, record_id)
);
CREATE INDEX idx_sync_records ON sync_bundle_records(record_type, record_id);

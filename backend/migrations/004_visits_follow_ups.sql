CREATE TABLE ai_suggestions (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    form_type     TEXT NOT NULL,
    values_json   TEXT NOT NULL,        -- suggested values, null = not suggested
    problems_json TEXT NOT NULL,        -- validation problems from the model output
    model         TEXT NOT NULL,
    duration_ms   INTEGER NOT NULL,
    created_by    TEXT NOT NULL REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE visits (
    id             TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    form_type      TEXT NOT NULL,
    visit_date     TEXT NOT NULL,       -- YYYY-MM-DD
    status         TEXT NOT NULL CHECK (status IN ('draft', 'final')),
    values_json    TEXT NOT NULL,
    sources_json   TEXT NOT NULL,       -- {field: "manual" | "ai_accepted" | "ai_edited"}
    note           TEXT,                -- original note, preserved verbatim
    suggestion_id  TEXT REFERENCES ai_suggestions(id),
    recorded_by    TEXT NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    finalized_at   TEXT
);
CREATE INDEX idx_visits_patient ON visits(patient_id, visit_date DESC);

CREATE TABLE follow_ups (
    id                  TEXT PRIMARY KEY,
    patient_id          TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    source_visit_id     TEXT REFERENCES visits(id),
    form_type           TEXT,           -- which form the follow-up visit should use
    due_date            TEXT NOT NULL,  -- YYYY-MM-DD
    reason              TEXT,
    status              TEXT NOT NULL CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    completed_visit_id  TEXT REFERENCES visits(id),
    completed_at        TEXT,
    created_by          TEXT NOT NULL REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_follow_ups_due ON follow_ups(status, due_date);
CREATE INDEX idx_follow_ups_patient ON follow_ups(patient_id);

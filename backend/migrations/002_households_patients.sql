CREATE TABLE households (
    id           TEXT PRIMARY KEY,
    barangay     TEXT NOT NULL,
    sitio        TEXT,
    address_line TEXT,
    contact_number TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE patients (
    id                    TEXT PRIMARY KEY,
    household_id          TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    full_name             TEXT NOT NULL,
    birth_date            TEXT,
    sex                   TEXT CHECK (sex IN ('female', 'male', 'intersex', 'unknown')),
    relationship_to_head  TEXT,
    contact_number        TEXT,
    is_household_head     INTEGER NOT NULL DEFAULT 0 CHECK (is_household_head IN (0, 1)),
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_patients_household ON patients(household_id);
CREATE INDEX idx_patients_name ON patients(full_name COLLATE NOCASE);
CREATE UNIQUE INDEX idx_one_household_head
    ON patients(household_id) WHERE is_household_head = 1;

CREATE VIRTUAL TABLE household_search USING fts5(
    household_id UNINDEXED,
    barangay,
    sitio,
    address_line,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER households_search_insert AFTER INSERT ON households BEGIN
    INSERT INTO household_search(rowid, household_id, barangay, sitio, address_line)
    VALUES (new.rowid, new.id, new.barangay, new.sitio, new.address_line);
END;

CREATE TRIGGER households_search_update AFTER UPDATE ON households BEGIN
    DELETE FROM household_search WHERE rowid = old.rowid;
    INSERT INTO household_search(rowid, household_id, barangay, sitio, address_line)
    VALUES (new.rowid, new.id, new.barangay, new.sitio, new.address_line);
END;

CREATE TRIGGER households_search_delete AFTER DELETE ON households BEGIN
    DELETE FROM household_search WHERE rowid = old.rowid;
END;

CREATE VIRTUAL TABLE patient_search USING fts5(
    patient_id UNINDEXED,
    full_name,
    contact_number,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER patients_search_insert AFTER INSERT ON patients BEGIN
    INSERT INTO patient_search(rowid, patient_id, full_name, contact_number)
    VALUES (new.rowid, new.id, new.full_name, new.contact_number);
END;

CREATE TRIGGER patients_search_update AFTER UPDATE ON patients BEGIN
    DELETE FROM patient_search WHERE rowid = old.rowid;
    INSERT INTO patient_search(rowid, patient_id, full_name, contact_number)
    VALUES (new.rowid, new.id, new.full_name, new.contact_number);
END;

CREATE TRIGGER patients_search_delete AFTER DELETE ON patients BEGIN
    DELETE FROM patient_search WHERE rowid = old.rowid;
END;

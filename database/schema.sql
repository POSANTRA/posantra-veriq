-- POSANTRA | VERIQ local database.
-- No uploaded image content is stored.

CREATE TABLE IF NOT EXISTS fingerprints (
    sha256      TEXT PRIMARY KEY,
    ahash       TEXT NOT NULL,
    phash       TEXT NOT NULL,
    dhash       TEXT NOT NULL,
    filename    TEXT,
    width       INTEGER,
    height      INTEGER,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    times_seen  INTEGER NOT NULL DEFAULT 1
);

-- Saved only when the user clicks "Save investigation record locally".
CREATE TABLE IF NOT EXISTS investigations (
    id                 TEXT PRIMARY KEY,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    investigation_type TEXT NOT NULL,
    input_hash         TEXT,
    input_label        TEXT,
    assessment         TEXT NOT NULL,
    evidence_strength  TEXT NOT NULL,
    report_json        TEXT NOT NULL
);
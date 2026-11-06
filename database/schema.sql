-- POSANTRA | VERIQ local database.
-- Fingerprints only: no image content is stored.
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
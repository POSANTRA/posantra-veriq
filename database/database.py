"""POSANTRA | VERIQ - local SQLite storage (Step 8).

Stores image fingerprints only (hashes, sanitised file name, dimensions,
timestamps). The image content is never stored. All queries are
parameterised.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MAX_RECORDS_COMPARED = 5000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def get_by_sha(sha256: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM fingerprints WHERE sha256 = ?", (sha256,)
        ).fetchone()
    return dict(row) if row else None


def save_fingerprint(sha256: str, ahash: str, phash: str, dhash: str,
                     filename: str, width: int, height: int) -> None:
    now = _now()
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO fingerprints
                    (sha256, ahash, phash, dhash, filename, width, height,
                     first_seen, last_seen, times_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(sha256) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    times_seen = times_seen + 1
                """,
                (sha256, ahash, phash, dhash, filename, width, height, now, now),
            )


def all_fingerprints(limit: int = MAX_RECORDS_COMPARED) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM fingerprints ORDER BY last_seen DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def count_fingerprints() -> int:
    with closing(_connect()) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0])


def clear_fingerprints() -> int:
    with closing(_connect()) as conn:
        with conn:
            cursor = conn.execute("DELETE FROM fingerprints")
            return cursor.rowcount
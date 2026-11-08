"""POSANTRA | VERIQ - local SQLite storage.

Stores image fingerprints (hashes, sanitised file name, dimensions, timestamps,
and a short note of what the file said about itself) and, only on explicit user
action, investigation records. Uploaded image content is never stored. All
queries are parameterised.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MAX_RECORDS_COMPARED = 5000
MAX_RECORD_BYTES = 2_000_000
ORIGINS = ("ai", "camera", "credentials")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    # Upgrade databases created before the 'origin' column existed.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(fingerprints)")}
    if "origin" not in columns:
        conn.execute("ALTER TABLE fingerprints ADD COLUMN origin TEXT NOT NULL DEFAULT ''")
        conn.commit()
    return conn


# ------------------------------------------------------------- fingerprints
def get_by_sha(sha256: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM fingerprints WHERE sha256 = ?", (sha256,)
        ).fetchone()
    return dict(row) if row else None


def save_fingerprint(sha256: str, ahash: str, phash: str, dhash: str,
                     filename: str, width: int, height: int, origin: str = "") -> None:
    origin = origin if origin in ORIGINS else ""
    now = _now()
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO fingerprints
                    (sha256, ahash, phash, dhash, filename, width, height,
                     first_seen, last_seen, times_seen, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    times_seen = times_seen + 1,
                    origin = CASE WHEN excluded.origin <> '' THEN excluded.origin
                                  ELSE fingerprints.origin END
                """,
                (sha256, ahash, phash, dhash, filename, width, height, now, now, origin),
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


# ----------------------------------------------------------- investigations
def save_investigation(data: dict) -> None:
    """Insert or update an investigation record (report data as JSON)."""
    inv_id = str(data.get("investigation_id") or "")
    if not inv_id:
        raise ValueError("The record has no investigation ID.")
    payload = json.dumps(data, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("The record is too large to save.")
    now = _now()
    values = (
        inv_id, now, now,
        str(data.get("investigation_type") or "Unknown"),
        str(data.get("input_hash") or ""),
        str(data.get("input_label") or "")[:300],
        str(data.get("headline") or "Not available"),
        str(data.get("strength_summary") or "Not available"),
        payload,
    )
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO investigations
                    (id, created_at, updated_at, investigation_type, input_hash,
                     input_label, assessment, evidence_strength, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    investigation_type = excluded.investigation_type,
                    input_hash = excluded.input_hash,
                    input_label = excluded.input_label,
                    assessment = excluded.assessment,
                    evidence_strength = excluded.evidence_strength,
                    report_json = excluded.report_json
                """,
                values,
            )


def list_investigations(limit: int = 100) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, created_at, investigation_type, input_label, assessment, "
            "evidence_strength FROM investigations ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_investigation(inv_id: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT report_json FROM investigations WHERE id = ?", (inv_id,)
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["report_json"])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def count_investigations() -> int:
    with closing(_connect()) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM investigations").fetchone()[0])


def clear_investigations() -> int:
    with closing(_connect()) as conn:
        with conn:
            cursor = conn.execute("DELETE FROM investigations")
            return cursor.rowcount
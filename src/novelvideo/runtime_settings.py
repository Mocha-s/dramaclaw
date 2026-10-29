"""Small CE-local runtime settings store shared by operational controls."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novelvideo.sqlite_pragmas import configure_sqlite_connection


def runtime_settings_db_path() -> Path:
    from novelvideo import config

    return Path(config.STATE_DIR) / "local" / "settings.db"


def _connect() -> sqlite3.Connection:
    path = runtime_settings_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def read_runtime_json(key: str, default: object) -> object:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value FROM runtime_settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(str(row["value"]))
        except (TypeError, json.JSONDecodeError):
            return default
    finally:
        conn.close()


def write_runtime_json(key: str, value: object) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO runtime_settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, encoded, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

"""SQLite connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(database_path: str) -> sqlite3.Connection:
    """Open a connection to `database_path` (or `:memory:`) and ensure the schema exists."""
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: FastAPI's sync dependencies can run on different
    # threadpool threads across requests/tests. This is a single-user local
    # tool with low concurrency, so relaxing SQLite's thread affinity is fine.
    conn = sqlite3.connect(database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn

"""SQLite connection management and in-place schema upgrades."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flight_fare_watcher.logging_config import get_logger

logger = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

#: Columns added after the first release, applied to existing databases by
#: `_apply_migrations`. `schema.sql` already creates them for a fresh database;
#: this list only exists so an upgrade keeps the fare history it has collected.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "watched_routes": {
        "adults": "INTEGER NOT NULL DEFAULT 1",
        "cabin": "TEXT NOT NULL DEFAULT 'economy'",
        "max_stops": "INTEGER",
        "last_checked_at": "TEXT",
        "last_status": "TEXT",
        "last_price": "REAL",
    },
    "fares": {
        "adults": "INTEGER NOT NULL DEFAULT 1",
        "cabin": "TEXT NOT NULL DEFAULT 'economy'",
        "airline": "TEXT",
        "carrier_code": "TEXT",
        "stops": "INTEGER",
        "duration_minutes": "INTEGER",
        "depart_time": "TEXT",
        "arrive_time": "TEXT",
        "booking_url": "TEXT",
    },
}

#: Indexes whose definition changed, which SQLite cannot ALTER. Dropping them
#: is safe - `schema.sql` recreates them straight afterwards.
_REBUILT_INDEXES: tuple[tuple[str, str], ...] = (
    # Gained adults/cabin, so one route can be watched for several party sizes.
    ("idx_watched_routes_unique", "adults"),
    ("idx_fares_route_lookup", "adults"),
)

#: SQLite waits this long for a lock before raising "database is locked". The
#: background watch job and a user's search write to the same file, so without
#: this the two can collide on a slow write.
_BUSY_TIMEOUT_MS = 5000


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Add any column or index this build expects but the database lacks."""
    for index_name, required_column in _REBUILT_INDEXES:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (index_name,)
        ).fetchone()
        if row is not None and row["sql"] and required_column not in row["sql"]:
            logger.info("migrating: rebuilding index %s", index_name)
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")

    for table, columns in _ADDED_COLUMNS.items():
        if not _table_exists(conn, table):
            continue  # fresh database; schema.sql creates it complete
        present = _existing_columns(conn, table)
        for column, definition in columns.items():
            if column in present:
                continue
            logger.info("migrating: adding %s.%s", table, column)
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def connect(database_path: str) -> sqlite3.Connection:
    """Open a connection to `database_path` (or `:memory:`) with the schema applied."""
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: FastAPI's sync dependencies can run on different
    # threadpool threads across requests/tests. This is a single-user local
    # tool with low concurrency, so relaxing SQLite's thread affinity is fine.
    conn = sqlite3.connect(database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    if database_path != ":memory:":
        # WAL lets the background watch job read while a search writes, which
        # plain rollback-journal mode serialises. Not valid for :memory:.
        conn.execute("PRAGMA journal_mode = WAL")

    _apply_migrations(conn)
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn

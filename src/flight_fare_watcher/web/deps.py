"""Shared FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

from flight_fare_watcher.config import get_settings
from flight_fare_watcher.db.database import connect


def get_db() -> Generator[sqlite3.Connection, None, None]:
    settings = get_settings()
    conn = connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()

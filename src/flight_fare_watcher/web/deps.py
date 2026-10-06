"""Shared FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

from fastapi import Request

from flight_fare_watcher.config import get_settings
from flight_fare_watcher.db.database import connect
from flight_fare_watcher.search.cache import SearchCache


def get_db() -> Generator[sqlite3.Connection, None, None]:
    settings = get_settings()
    conn = connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def get_search_cache(request: Request) -> SearchCache:
    """The app-wide search cache, created once in the app's lifespan."""
    return request.app.state.search_cache

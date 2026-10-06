"""Health/status endpoints: provider scrape health and airport autocomplete.

Separate from routes_search.py because these are read-only, cheap lookups with
no scraping involved - the airport list is static and scrape_health is a
simple table read.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from flight_fare_watcher.airports import Airport, search_airports
from flight_fare_watcher.config import get_settings
from flight_fare_watcher.db import repository
from flight_fare_watcher.scrapers.registry import SITE_DESCRIPTIONS
from flight_fare_watcher.web.deps import get_db

router = APIRouter()


@router.get("/api/airports")
def airports(q: str = Query(default="", max_length=64)) -> list[dict]:
    """Autocomplete suggestions for the origin/destination fields."""
    results: list[Airport] = search_airports(q)
    return [
        {"code": a.code, "city": a.city, "name": a.name, "country": a.country, "label": a.label}
        for a in results
    ]


@router.get("/api/health")
def health(conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Per-provider last-known status, for a small status strip in the UI."""
    settings = get_settings()
    enabled = set(settings.enabled_site_list)
    recorded = {row["site"]: row for row in repository.latest_scrape_health(conn)}

    providers = []
    for site in sorted(enabled):
        record = recorded.get(site)
        providers.append(
            {
                "site": site,
                "description": SITE_DESCRIPTIONS.get(site, site),
                "last_status": record["status"] if record else None,
                "last_checked_at": record["checked_at"] if record else None,
                "detail": record["detail"] if record else None,
            }
        )
    return {"providers": providers}

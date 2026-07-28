"""On-demand search endpoint."""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from flight_fare_watcher.config import get_settings
from flight_fare_watcher.db import repository
from flight_fare_watcher.scrapers.registry import build_enabled_adapters
from flight_fare_watcher.search.orchestrator import SearchResponse, run_search
from flight_fare_watcher.web.deps import get_db

router = APIRouter()


class SearchRequest(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None


@router.post("/api/search", response_model=SearchResponse)
async def search_flights(request: SearchRequest, conn: sqlite3.Connection = Depends(get_db)) -> SearchResponse:
    settings = get_settings()
    adapters = build_enabled_adapters(
        settings.enabled_site_list,
        scrape_delay_min=settings.scrape_delay_min_seconds,
        scrape_delay_max=settings.scrape_delay_max_seconds,
    )
    response = await run_search(
        adapters,
        request.origin,
        request.destination,
        request.depart_date,
        request.return_date,
        headless=settings.playwright_headless,
    )

    # Opportunistically build price history for this route even without a saved watch.
    for fare in response.fares:
        repository.insert_fare(conn, fare)

    return response

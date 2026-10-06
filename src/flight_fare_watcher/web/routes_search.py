"""On-demand search and booking-link endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from flight_fare_watcher.config import get_settings
from flight_fare_watcher.db import repository
from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.registry import (
    SITE_DESCRIPTIONS,
    build_adapters_from_settings,
)
from flight_fare_watcher.search.orchestrator import (
    SearchResponse,
    resolve_one_booking_link,
    run_search,
)
from flight_fare_watcher.web.deps import get_db, get_search_cache

logger = get_logger(__name__)

router = APIRouter()


class SearchRequest(SearchQuery):
    """A search, plus the option to bypass the result cache."""

    refresh: bool = False


class BookingLinkRequest(SearchQuery):
    """Resolve a booking link for one already-returned fare."""

    fare: FareResult


@router.post("/api/search", response_model=SearchResponse)
async def search_flights(
    request: SearchRequest,
    http_request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> SearchResponse:
    settings = get_settings()
    query = SearchQuery(**request.model_dump(exclude={"refresh"}))
    cache = get_search_cache(http_request)

    if request.refresh:
        await cache.invalidate(query)
    else:
        cached = await cache.get(query)
        if cached is not None:
            return cached

    response = await run_search(
        build_adapters_from_settings(settings),
        query,
        headless=settings.playwright_headless,
        booking_link_resolve_count=settings.booking_link_resolve_count,
    )

    # Opportunistically build price history for this route even without a
    # saved watch, so a later watch on the same route starts with context.
    repository.record_search_fares(conn, query, response.fares)
    await cache.put(query, response)
    return response


@router.post("/api/booking-link")
async def booking_link(request: BookingLinkRequest) -> dict:
    """Resolve a link to one specific flight's booking page.

    Separate from `/api/search` because resolution costs a page load and a
    click (~8s measured) per fare. The search resolves only the cheapest few
    (`BOOKING_LINK_RESOLVE_COUNT`); this endpoint covers any other row the
    user actually wants to book.
    """
    settings = get_settings()
    query = SearchQuery(**request.model_dump(exclude={"fare"}))
    url = await resolve_one_booking_link(
        build_adapters_from_settings(settings),
        query,
        request.fare,
        headless=settings.playwright_headless,
    )
    if url is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Could not find that flight on the results page - it may no longer "
                "be offered at that price. Try searching again."
            ),
        )
    return {"booking_url": url}


@router.get("/api/providers")
def list_providers() -> dict:
    """Which providers are enabled, so the UI can explain where fares come from."""
    settings = get_settings()
    enabled = settings.enabled_site_list
    return {
        "enabled": enabled,
        "descriptions": {site: SITE_DESCRIPTIONS.get(site, site) for site in enabled},
    }

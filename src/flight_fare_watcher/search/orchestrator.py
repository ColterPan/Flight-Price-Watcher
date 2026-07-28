"""Fans out a route search to all enabled site adapters concurrently and aggregates results."""

from __future__ import annotations

import asyncio
from datetime import date

from playwright.async_api import BrowserContext, async_playwright
from pydantic import BaseModel

from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome
from flight_fare_watcher.scrapers.base import FlightSiteAdapter, new_context

logger = get_logger(__name__)


class SearchResponse(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    fares: list[FareResult]
    site_statuses: dict[str, str]


async def _run_one_adapter(
    adapter: FlightSiteAdapter,
    context: BrowserContext,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
) -> ScrapeOutcome:
    try:
        return await adapter.search(origin, destination, depart_date, return_date, context)
    except Exception as exc:  # noqa: BLE001 - one adapter's bug must not sink the whole search
        logger.exception("adapter %s raised unexpectedly", adapter.site_name)
        return ScrapeOutcome(site=adapter.site_name, status="error", diagnostic=str(exc))


def build_response(
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
    outcomes: list[ScrapeOutcome],
) -> SearchResponse:
    all_fares: list[FareResult] = [fare for outcome in outcomes for fare in outcome.fares]
    all_fares.sort(key=lambda f: f.price)
    site_statuses = {outcome.site: outcome.status for outcome in outcomes}
    return SearchResponse(
        origin=origin,
        destination=destination,
        depart_date=depart_date,
        return_date=return_date,
        fares=all_fares,
        site_statuses=site_statuses,
    )


async def run_search(
    adapters: list[FlightSiteAdapter],
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
    headless: bool = True,
) -> SearchResponse:
    """Launch a browser, run every adapter concurrently, and aggregate the results.

    Each adapter gets its own browser context so one site's cookies/state
    can't leak into another's, and so one adapter crashing mid-navigation
    can't take down a sibling adapter's page.
    """
    if not adapters:
        return build_response(origin, destination, depart_date, return_date, [])

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            contexts = await asyncio.gather(*[new_context(browser) for _ in adapters])
            try:
                outcomes = await asyncio.gather(
                    *[
                        _run_one_adapter(adapter, context, origin, destination, depart_date, return_date)
                        for adapter, context in zip(adapters, contexts)
                    ]
                )
            finally:
                await asyncio.gather(*[context.close() for context in contexts])
        finally:
            await browser.close()

    return build_response(origin, destination, depart_date, return_date, list(outcomes))

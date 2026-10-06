"""Fans one search out to every enabled provider concurrently and aggregates results."""

from __future__ import annotations

import asyncio
from datetime import date

from playwright.async_api import BrowserContext, async_playwright
from pydantic import BaseModel

from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.base import FlightSiteAdapter, new_context

logger = get_logger(__name__)


class SearchResponse(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    fares: list[FareResult]
    site_statuses: dict[str, str]
    #: Per-provider explanation, shown in the UI next to a non-ok status so a
    #: blocked scraper or an unconfigured API is self-explanatory.
    site_diagnostics: dict[str, str] = {}
    #: True when this response was served from the short-lived result cache.
    from_cache: bool = False


async def _run_one_adapter(
    adapter: FlightSiteAdapter,
    context: BrowserContext | None,
    query: SearchQuery,
) -> ScrapeOutcome:
    try:
        return await adapter.search(query, context)
    except Exception as exc:  # noqa: BLE001 - one adapter's bug must not sink the search
        logger.exception("adapter %s raised unexpectedly", adapter.site_name)
        return ScrapeOutcome(site=adapter.site_name, status="error", diagnostic=str(exc))


def build_response(query: SearchQuery, outcomes: list[ScrapeOutcome]) -> SearchResponse:
    """Merge every provider's outcome into one price-sorted response."""
    all_fares: list[FareResult] = [fare for outcome in outcomes for fare in outcome.fares]
    all_fares.sort(key=lambda fare: fare.price)
    return SearchResponse(
        origin=query.origin,
        destination=query.destination,
        depart_date=query.depart_date,
        return_date=query.return_date,
        fares=all_fares,
        site_statuses={outcome.site: outcome.status for outcome in outcomes},
        site_diagnostics={
            outcome.site: outcome.diagnostic for outcome in outcomes if outcome.diagnostic
        },
    )


async def _resolve_booking_links(
    adapters: list[FlightSiteAdapter],
    contexts: dict[str, BrowserContext],
    query: SearchQuery,
    fares: list[FareResult],
    count: int,
) -> None:
    """Attach a per-flight booking link to the `count` cheapest fares, in place.

    Sequential by design: resolution drives a real page, and running several at
    once in one browser context was measured to make every one of them fail.
    Any failure leaves that fare with its search `deep_link`.
    """
    if count <= 0:
        return
    by_site = {adapter.site_name: adapter for adapter in adapters}

    for fare in fares[:count]:
        adapter = by_site.get(fare.site)
        if adapter is None:
            continue
        try:
            url = await adapter.resolve_booking_url(query, fare, contexts.get(fare.site))
        except Exception:  # noqa: BLE001 - enrichment is never fatal
            logger.exception("booking link resolution raised for %s", fare.site)
            continue
        if url:
            fare.booking_url = url


async def run_search(
    adapters: list[FlightSiteAdapter],
    query: SearchQuery,
    headless: bool = True,
    booking_link_resolve_count: int = 0,
) -> SearchResponse:
    """Run every provider for `query` concurrently and aggregate the results.

    Each browser-based provider gets its own `BrowserContext` so one site's
    cookies and state cannot leak into another's, and so one adapter crashing
    mid-navigation cannot take down a sibling's page. API-based providers
    (`needs_browser = False`) are run without one, and if no enabled provider
    needs a browser, Playwright is never launched at all.
    """
    if not adapters:
        return build_response(query, [])

    browser_adapters = [adapter for adapter in adapters if adapter.needs_browser]
    if not browser_adapters:
        outcomes = await asyncio.gather(
            *[_run_one_adapter(adapter, None, query) for adapter in adapters]
        )
        return build_response(query, list(outcomes))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        try:
            contexts = dict(
                zip(
                    [adapter.site_name for adapter in browser_adapters],
                    await asyncio.gather(
                        *[new_context(browser) for _ in browser_adapters]
                    ),
                )
            )
            try:
                outcomes = list(
                    await asyncio.gather(
                        *[
                            _run_one_adapter(
                                adapter,
                                contexts.get(adapter.site_name),
                                query,
                            )
                            for adapter in adapters
                        ]
                    )
                )
                response = build_response(query, outcomes)
                await _resolve_booking_links(
                    adapters, contexts, query, response.fares, booking_link_resolve_count
                )
            finally:
                await asyncio.gather(*[context.close() for context in contexts.values()])
        finally:
            await browser.close()

    return response


async def resolve_one_booking_link(
    adapters: list[FlightSiteAdapter],
    query: SearchQuery,
    fare: FareResult,
    headless: bool = True,
) -> str | None:
    """Resolve a booking link for a single fare, launching a browser just for it.

    Backs the on-demand "get the direct link for this flight" action, so the
    user can get a booking link for any row without paying that cost for
    every row of every search.
    """
    adapter = next((item for item in adapters if item.site_name == fare.site), None)
    if adapter is None:
        return None

    if not adapter.needs_browser:
        return await adapter.resolve_booking_url(query, fare, None)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        try:
            context = await new_context(browser)
            try:
                return await adapter.resolve_booking_url(query, fare, context)
            finally:
                await context.close()
        finally:
            await browser.close()

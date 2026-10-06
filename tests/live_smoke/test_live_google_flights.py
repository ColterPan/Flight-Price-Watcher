"""Manual-only smoke test against the real Google Flights site.

Not collected by default `pytest` (see pyproject.toml `testpaths`) and not run
in CI - run this by hand when you suspect the adapter broke:

    pytest tests/live_smoke/test_live_google_flights.py -v
"""

from datetime import date, timedelta

import pytest
from playwright.async_api import async_playwright

from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.base import new_context
from flight_fare_watcher.scrapers.google_flights import GoogleFlightsAdapter, build_search_url
from flight_fare_watcher.scrapers.google_flights_booking import resolve_booking_url


@pytest.mark.asyncio
async def test_live_search_returns_ok_with_fares():
    adapter = GoogleFlightsAdapter(scrape_delay_min=0.5, scrape_delay_max=1.0)
    query = SearchQuery(origin="JFK", destination="LAX", depart_date=date.today() + timedelta(days=45))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await new_context(browser)
        try:
            outcome = await adapter.search(query, context)
        finally:
            await context.close()
            await browser.close()

    print(f"status={outcome.status} fare_count={len(outcome.fares)}")
    if outcome.fares:
        cheapest = min(outcome.fares, key=lambda f: f.price)
        print(f"cheapest: {cheapest.airline} ${cheapest.price} -> {cheapest.deep_link}")

    assert outcome.status == "ok", f"expected ok, got {outcome.status}: {outcome.diagnostic}"
    assert len(outcome.fares) > 0
    # Every fare must come out deduplicated and with itinerary detail - a
    # regression here is exactly the "64 duplicate rows, garbage airline
    # field" bug this adapter was rewritten to fix.
    assert all(fare.depart_time and fare.arrive_time for fare in outcome.fares)
    assert all(fare.stops is not None for fare in outcome.fares)


@pytest.mark.asyncio
async def test_live_round_trip_booking_link_resolves_to_a_booking_url():
    """The two-step round-trip flow: outbound click -> return-leg click -> /booking."""
    adapter = GoogleFlightsAdapter(scrape_delay_min=0.5, scrape_delay_max=1.0)
    query = SearchQuery(
        origin="JFK",
        destination="LAX",
        depart_date=date.today() + timedelta(days=45),
        return_date=date.today() + timedelta(days=52),
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await new_context(browser)
        try:
            outcome = await adapter.search(query, context)
            assert outcome.status == "ok" and outcome.fares

            cheapest = min(outcome.fares, key=lambda f: f.price)
            url = await resolve_booking_url(context, build_search_url(query), query, cheapest)
        finally:
            await context.close()
            await browser.close()

    print(f"booking_url={url}")
    assert url is not None
    assert "/travel/flights/booking" in url
    assert "tfs=" in url

"""Manual-only smoke test against the real Google Flights site.

Not collected by default `pytest` (see pyproject.toml `testpaths`) and not run
in CI - run this by hand when you suspect the adapter broke:

    pytest tests/live_smoke/test_live_google_flights.py -v
"""

from datetime import date, timedelta

import pytest
from playwright.async_api import async_playwright

from flight_fare_watcher.scrapers.base import new_context
from flight_fare_watcher.scrapers.google_flights import GoogleFlightsAdapter


@pytest.mark.asyncio
async def test_live_search_returns_ok_with_fares():
    adapter = GoogleFlightsAdapter(scrape_delay_min=0.5, scrape_delay_max=1.0)
    depart = date.today() + timedelta(days=45)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await new_context(browser)
        try:
            outcome = await adapter.search("JFK", "LAX", depart, None, context)
        finally:
            await context.close()
            await browser.close()

    print(f"status={outcome.status} fare_count={len(outcome.fares)}")
    if outcome.fares:
        cheapest = min(outcome.fares, key=lambda f: f.price)
        print(f"cheapest: {cheapest.airline} ${cheapest.price} -> {cheapest.deep_link}")

    assert outcome.status == "ok", f"expected ok, got {outcome.status}: {outcome.diagnostic}"
    assert len(outcome.fares) > 0

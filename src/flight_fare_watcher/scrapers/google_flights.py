"""Google Flights adapter.

Navigation uses Google's own shareable search-link format (`?q=...`) rather
than UI form-filling - see docs/recon_notes.md for why, and for the exact
result-row selector this was built against.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from playwright.async_api import BrowserContext

from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome
from flight_fare_watcher.scrapers.base import (
    FlightSiteAdapter,
    RetryableScrapeError,
    polite_delay,
    with_retry,
)

logger = get_logger(__name__)

RESULT_ROW_SELECTOR = "li.pIav2d"
SETTLE_WAIT_MS = 6000
NAV_TIMEOUT_MS = 45000

_TIME_RE = re.compile(r"\d{1,2}:\d{2}\s?[AP]M")
_DURATION_RE = re.compile(r"\d+\s?hr\s?\d+\s?min")
_PRICE_RE = re.compile(r"\$([\d,]+(?:\.\d{2})?)")


def build_search_url(
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
) -> str:
    trip = f"{depart_date.isoformat()} through {return_date.isoformat()}" if return_date else f"{depart_date.isoformat()} one way"
    query = f"Flights from {origin} to {destination} on {trip}"
    return f"https://www.google.com/travel/flights?q={quote(query)}&hl=en&gl=US&curr=USD"


def parse_flight_row(row_text: str) -> dict | None:
    """Extract airline + price from one result row's innerText.

    Returns None if the row doesn't look like a parseable fare row (used to
    skip promo/ad rows without treating the whole scrape as broken).
    """
    times = list(_TIME_RE.finditer(row_text))
    price_match = _PRICE_RE.search(row_text)
    if len(times) < 2 or price_match is None:
        return None

    try:
        price = Decimal(price_match.group(1).replace(",", ""))
    except InvalidOperation:
        return None

    duration_match = _DURATION_RE.search(row_text)
    segment_end = duration_match.start() if duration_match else min(times[1].end() + 60, len(row_text))
    airline_segment = row_text[times[1].end() : segment_end]
    airline_segment = re.sub(r"^\+?\d+\s*", "", airline_segment.strip())
    airline = re.sub(r"\s+", " ", airline_segment).strip() or None

    return {"airline": airline, "price": price}


class GoogleFlightsAdapter(FlightSiteAdapter):
    site_name = "google_flights"

    def __init__(self, scrape_delay_min: float = 1.5, scrape_delay_max: float = 4.0) -> None:
        self._delay_min = scrape_delay_min
        self._delay_max = scrape_delay_max

    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date | None,
        context: BrowserContext,
    ) -> ScrapeOutcome:
        url = build_search_url(origin, destination, depart_date, return_date)
        try:
            page_state = await with_retry(lambda: self._fetch_rows(context, url))
        except RetryableScrapeError as exc:
            logger.warning("google_flights: navigation failed after retries: %s", exc)
            return ScrapeOutcome(site=self.site_name, status="error", diagnostic=str(exc))
        except Exception as exc:  # noqa: BLE001 - adapter must never propagate
            logger.exception("google_flights: unexpected error")
            return ScrapeOutcome(site=self.site_name, status="error", diagnostic=str(exc))

        rows_text = page_state["rows"]
        title = page_state["title"]
        if len(rows_text) == 0:
            # Google Flights renders a normal "Google Flights"-titled page even
            # when a route has zero results; if the title looks off, the page
            # likely isn't the expected results page at all (blocked/challenge).
            if "Google Flights" in title:
                return ScrapeOutcome(site=self.site_name, status="no_results")
            return ScrapeOutcome(
                site=self.site_name,
                status="blocked_or_structure_changed",
                diagnostic=f"no result rows and unexpected page title: {title!r}",
            )

        scraped_at = datetime.now()
        fares: list[FareResult] = []
        for text in rows_text:
            parsed = parse_flight_row(text)
            if parsed is None:
                continue
            fares.append(
                FareResult(
                    site=self.site_name,
                    origin=origin,
                    destination=destination,
                    depart_date=depart_date,
                    return_date=return_date,
                    price=parsed["price"],
                    currency="USD",
                    deep_link=url,
                    scraped_at=scraped_at,
                    airline=parsed["airline"],
                )
            )

        if not fares:
            return ScrapeOutcome(
                site=self.site_name,
                status="blocked_or_structure_changed",
                diagnostic="rows found but none were parseable - page structure may have changed",
            )
        return ScrapeOutcome(site=self.site_name, status="ok", fares=fares)

    async def _fetch_rows(self, context: BrowserContext, url: str) -> dict:
        await polite_delay(self._delay_min, self._delay_max)
        page = await context.new_page()
        try:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception as exc:
                raise RetryableScrapeError(f"navigation timeout/error: {exc}") from exc

            await page.wait_for_timeout(SETTLE_WAIT_MS)

            locator = page.locator(RESULT_ROW_SELECTOR)
            count = await locator.count()
            texts = [await locator.nth(i).inner_text() for i in range(count)]
            return {"rows": texts, "title": await page.title()}
        finally:
            await page.close()

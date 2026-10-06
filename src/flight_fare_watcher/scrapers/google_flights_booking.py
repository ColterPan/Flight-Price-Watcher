"""Resolve a Google Flights result row to a link for that one itinerary.

## Why this exists

A search-results URL is the same for all 30 fares on the page, so "book the
cheapest flight" means the user lands on a list and has to find the row again.
This module turns one chosen fare into a URL that opens *that flight's*
booking panel directly.

## What it returns, and why that URL and not another

Clicking a result row navigates the page to:

    https://www.google.com/travel/flights/booking?tfs=<base64>&tfu=<base64>&hl=en&gl=US&curr=USD

That is the link this module returns. Verified live: it is shareable, carries
no session token or timestamp, and opens on the chosen flight's "Booking
options" panel with the per-airline prices and `Continue` buttons.

**Round trips need a second click.** Clicking an outbound row does not reach
`/booking` directly - it navigates to `/travel/flights/search?tfs=...`, a
return-flight-selection step showing the return leg's own list of
`li.pIav2d` rows. Only *one* of those return rows carries the round-trip total
price already shown on the outbound row (confirmed live: of 9 return options,
exactly one matched the $409 total; the rest were higher) - clicking that one
is what reaches `/booking`. One-way searches skip this step entirely.

Following `Continue` one step further *does* reach the airline's own checkout
(confirmed landing on a real `jetblue.com/booking/trip-summary?...` URL with
genuine `flightNumbers` and `fareBasisCode` params), and that was considered
as the thing to return. It is deliberately **not** used, for two reasons:

1. That URL carries `t=<epoch>` and `sig=<signature>` query params - it is
   time-limited and tied to the session that generated it, so persisting it in
   the `fares` table would produce links that are dead by the time an email
   alert is read.
2. The airline then serves a bot-detection interstitial ("Client Challenge")
   to the automated browser, so even immediately the final page is not what a
   human would see.

The `/travel/flights/booking` URL has neither problem and is still one click
from the airline's checkout.

## Cost

Resolution needs a real page load plus a click - about 8 seconds per fare,
measured. So it runs for the cheapest few fares only
(`BOOKING_LINK_RESOLVE_COUNT`), and any other row is resolved on demand via
`POST /api/booking-link`. Attempting all 30 rows would multiply both the
search time and the request load on Google by 30.
"""

from __future__ import annotations

from playwright.async_api import BrowserContext

from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.google_flights_parse import parse_aria_label

logger = get_logger(__name__)

NAV_TIMEOUT_MS = 45000
#: Google streams results in after load; clicking before the list settles
#: selects the wrong row or misses the click entirely.
SETTLE_WAIT_MS = 6000
#: How long to wait for the URL to become a /booking?tfs=... URL after the click.
URL_POLL_ATTEMPTS = 30
URL_POLL_INTERVAL_MS = 500

BOOKING_URL_MARKER = "/travel/flights/booking"
#: The intermediate return-leg-selection step a round trip lands on after the
#: outbound row is clicked - also has `tfs=`, so it must be checked first.
RETURN_SELECTION_URL_MARKER = "/travel/flights/search"


def is_booking_url(url: str) -> bool:
    """Whether `url` is a per-itinerary Google Flights booking URL."""
    return BOOKING_URL_MARKER in url and "tfs=" in url


def is_return_selection_url(url: str) -> bool:
    """Whether `url` is the round-trip return-leg-selection step."""
    return RETURN_SELECTION_URL_MARKER in url and "tfs=" in url and not is_booking_url(url)


def fares_match(candidate: dict, target: FareResult) -> bool:
    """Whether a parsed row describes the same offer as `target`.

    Matched on data rather than row position: the fare list is sorted by price
    while the page lists Google's "Best flights" picks first, so the cheapest
    fare is not reliably the first row.
    """
    if candidate["price"] != target.price:
        return False
    for field in ("depart_time", "arrive_time", "stops"):
        expected = getattr(target, field)
        if expected is not None and candidate.get(field) != expected:
            return False
    return True


async def _find_matching_row(page, depart_date, matcher):
    """The first visible `li.pIav2d` row whose parsed itinerary satisfies `matcher`."""
    rows = page.locator("li.pIav2d")
    for index in range(await rows.count()):
        row = rows.nth(index)
        if not await row.is_visible():
            continue  # off-screen mirror copy; see google_flights.py
        link = row.locator('div[role="link"][aria-label]').first
        if await link.count() == 0:
            continue
        aria = await link.get_attribute("aria-label")
        parsed = parse_aria_label(aria or "", depart_date)
        if parsed is not None and matcher(parsed):
            return link
    return None


async def _wait_for_url(page, predicate, attempts: int = URL_POLL_ATTEMPTS) -> bool:
    for _ in range(attempts):
        await page.wait_for_timeout(URL_POLL_INTERVAL_MS)
        if predicate(page.url):
            return True
    return False


async def resolve_booking_url(
    context: BrowserContext,
    search_url: str,
    query: SearchQuery,
    fare: FareResult,
) -> str | None:
    """Return a booking URL for `fare`, or `None` if it could not be resolved.

    Never raises: a failure here must degrade the fare to its search link, not
    fail the surrounding search.
    """
    page = await context.new_page()
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        await page.wait_for_timeout(SETTLE_WAIT_MS)

        outbound_row = await _find_matching_row(
            page, query.depart_date, lambda parsed: fares_match(parsed, fare)
        )
        if outbound_row is None:
            logger.info(
                "booking link: no row on the page matches %s %s at %s - "
                "the fare has probably changed since the search",
                fare.site,
                fare.airline,
                fare.price,
            )
            return None

        # force=True: the row's clickable overlay is covered by its own
        # content, so a normal click is refused as "intercepted".
        await outbound_row.click(force=True)

        if not await _wait_for_url(page, lambda url: is_booking_url(url) or is_return_selection_url(url)):
            logger.info("booking link: URL never advanced (still %s)", page.url[:120])
            return None

        if is_booking_url(page.url):
            logger.info("booking link resolved for %s at %s", fare.airline, fare.price)
            return page.url

        # Round trip: the outbound click landed on the return-leg-selection
        # step instead. Exactly one return option carries the same total
        # price already shown on the outbound row - that is the one Google
        # paired with it (verified live: of 9 return rows, only 1 matched).
        return_row = await _find_matching_row(
            page, fare.return_date or query.depart_date, lambda parsed: parsed["price"] == fare.price
        )
        if return_row is None:
            logger.info(
                "booking link: outbound matched but no return leg at the same total price (%s)",
                fare.price,
            )
            return None

        await return_row.click(force=True)
        if await _wait_for_url(page, is_booking_url):
            logger.info("booking link resolved for %s at %s (round trip)", fare.airline, fare.price)
            return page.url

        logger.info("booking link: return leg selected but URL never reached /booking (still %s)", page.url[:120])
        return None
    except Exception as exc:  # noqa: BLE001 - optional enrichment, never fatal
        logger.warning("booking link resolution failed: %s", exc)
        return None
    finally:
        await page.close()

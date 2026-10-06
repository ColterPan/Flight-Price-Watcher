"""Google Flights adapter.

Navigation uses Google's own shareable search-link format (`?q=...`) rather
than UI form-filling - see docs/recon_notes.md for why.

Two things here exist because live recon proved they were needed, and both are
easy to regress if someone "simplifies" this file:

1. **Only visible rows count.** Google renders the whole result list twice -
   once on screen and once in an off-screen mirror tree whose `innerText` has
   the accessibility strings inlined. Both copies match `li.pIav2d`, so
   scraping without a visibility filter returns every fare twice, with the
   duplicate's airline field full of junk like
   "on Fri, Nov 20 - 9:22 AM9:22 AMAmerican". Measured: 64 rows -> 32 real.
2. **Parse the aria-label, not the innerText.** See
   `google_flights_parse.py` for the reasoning and the grammar.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from playwright.async_api import BrowserContext

from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers import google_flights_booking
from flight_fare_watcher.scrapers.base import (
    FlightSiteAdapter,
    RetryableScrapeError,
    polite_delay,
    with_retry,
)
from flight_fare_watcher.scrapers.google_flights_parse import parse_aria_label

logger = get_logger(__name__)

RESULT_ROW_SELECTOR = "li.pIav2d"
SETTLE_WAIT_MS = 7000
NAV_TIMEOUT_MS = 45000

#: Runs in the page. Returns one entry per `li.pIav2d` with the three things
#: the parser needs: whether the row is the on-screen copy, the itinerary
#: aria-label, and the carrier's IATA code recovered from its logo URL
#: (e.g. `airline_logos/70px/AA.png` -> `AA`), which Google exposes nowhere
#: else in the row. Kept in sync with scripts/capture_google_flights_fixture.py.
_EXTRACT_ROWS_JS = r"""(selector) => {
  const rows = [...document.querySelectorAll(selector)];
  return {
    title: document.title,
    bodyText: (document.body.innerText || '').slice(0, 2000),
    rows: rows.map((row) => {
      const link = row.querySelector('div[role="link"][aria-label]');
      const logo = row.querySelector('[style*="airline_logos"]');
      let carrier = null;
      if (logo) {
        const match = (logo.getAttribute('style') || '')
          .match(/airline_logos\/[^/]+\/([A-Z0-9]{2,3})\.png/);
        if (match) carrier = match[1];
      }
      return {
        visible: row.getBoundingClientRect().height > 0 && !!row.offsetParent,
        aria: link ? link.getAttribute('aria-label') : null,
        carrier,
      };
    }),
  };
}"""


#: Cabin wording Google's query parser understands. Verified live: asking for
#: "business class" on JFK-LAX moved the cheapest fare from $294 to $1299, so
#: these are genuinely applied rather than silently ignored.
_CABIN_PHRASES: dict[str, str] = {
    "economy": "",
    "premium_economy": " premium economy",
    "business": " business class",
    "first": " first class",
}


def build_search_url(query: SearchQuery) -> str:
    """Google's shareable search-link format for one search.

    `hl`/`gl`/`curr` pin language, region and currency so parsing never depends
    on the browser's ambient locale.

    Passengers, cabin and "nonstop" are expressed in the natural-language `q`
    text because that is the only input format this adapter has verified. Each
    was confirmed to change the returned fares (see `_CABIN_PHRASES`); a
    `max_stops` above 0 has no verified query wording, so it is applied as a
    post-filter in `_build_outcome` instead of being guessed at here.
    """
    trip = (
        f"{query.depart_date.isoformat()} through {query.return_date.isoformat()}"
        if query.return_date
        else f"{query.depart_date.isoformat()} one way"
    )
    text = f"Flights from {query.origin} to {query.destination} on {trip}"
    if query.adults > 1:
        text += f" for {query.adults} adults"
    text += _CABIN_PHRASES.get(query.cabin, "")
    if query.max_stops == 0:
        text += " nonstop"
    return f"https://www.google.com/travel/flights?q={quote(text)}&hl=en&gl=US&curr=USD"


def dedupe_fares(fares: list[FareResult]) -> list[FareResult]:
    """Drop repeated itineraries, preserving the order given.

    Google lists its "Best flights" picks in their own `<ul>` and may repeat
    them in the full "All flights" list below, so one scrape can legitimately
    contain the same itinerary twice.
    """
    seen: set[tuple] = set()
    unique: list[FareResult] = []
    for fare in fares:
        key = fare.itinerary_key()
        if key in seen:
            continue
        seen.add(key)
        unique.append(fare)
    return unique


class GoogleFlightsAdapter(FlightSiteAdapter):
    site_name = "google_flights"

    def __init__(self, scrape_delay_min: float = 1.5, scrape_delay_max: float = 4.0) -> None:
        self._delay_min = scrape_delay_min
        self._delay_max = scrape_delay_max

    async def search(self, query: SearchQuery, context: BrowserContext | None) -> ScrapeOutcome:
        if context is None:  # pragma: no cover - orchestrator always supplies one
            return ScrapeOutcome(
                site=self.site_name,
                status="error",
                diagnostic="google_flights needs a browser context",
            )
        url = build_search_url(query)
        try:
            page_state = await with_retry(lambda: self._fetch_rows(context, url))
        except RetryableScrapeError as exc:
            logger.warning("google_flights: navigation failed after retries: %s", exc)
            return ScrapeOutcome(site=self.site_name, status="error", diagnostic=str(exc))
        except Exception as exc:  # noqa: BLE001 - adapter must never propagate
            logger.exception("google_flights: unexpected error")
            return ScrapeOutcome(site=self.site_name, status="error", diagnostic=str(exc))

        return self._build_outcome(page_state, query, url)

    async def resolve_booking_url(
        self,
        query: SearchQuery,
        fare: FareResult,
        context: BrowserContext | None,
    ) -> str | None:
        if context is None:
            return None
        return await google_flights_booking.resolve_booking_url(
            context, build_search_url(query), query, fare
        )

    def _build_outcome(self, page_state: dict, query: SearchQuery, url: str) -> ScrapeOutcome:
        all_rows: list[dict] = page_state["rows"]
        title: str = page_state["title"]
        visible_rows = [row for row in all_rows if row.get("visible")]

        if not visible_rows:
            # Google renders a normal "... | Google Flights"-titled page even
            # when a route genuinely has zero results; if the title looks off,
            # the page probably is not the results page at all.
            if "Google Flights" in title:
                return ScrapeOutcome(site=self.site_name, status="no_results")
            return ScrapeOutcome(
                site=self.site_name,
                status="blocked_or_structure_changed",
                diagnostic=f"no visible result rows and unexpected page title: {title!r}",
            )

        logger.info(
            "google_flights: %s %s rows (%s visible, %s mirrored)",
            query.route_label,
            len(all_rows),
            len(visible_rows),
            len(all_rows) - len(visible_rows),
        )

        scraped_at = datetime.now()
        fallback_trip = "round_trip" if query.is_round_trip else "one_way"
        fares: list[FareResult] = []
        for row in visible_rows:
            parsed = parse_aria_label(row.get("aria") or "", query.depart_date)
            if parsed is None:
                continue
            fares.append(
                FareResult(
                    site=self.site_name,
                    origin=query.origin,
                    destination=query.destination,
                    depart_date=query.depart_date,
                    return_date=query.return_date,
                    deep_link=url,
                    scraped_at=scraped_at,
                    carrier_code=row.get("carrier"),
                    **{**parsed, "trip_type": parsed["trip_type"] or fallback_trip},
                )
            )

        if not fares:
            return ScrapeOutcome(
                site=self.site_name,
                status="blocked_or_structure_changed",
                diagnostic=(
                    f"{len(visible_rows)} visible rows found but none were parseable - "
                    "the aria-label grammar has probably changed; re-run "
                    "scripts/capture_google_flights_fixture.py"
                ),
            )

        unique = dedupe_fares(fares)
        if query.max_stops is not None:
            # Applied here rather than in the query text: only "nonstop" has a
            # verified query wording, so a limit of 1-3 is enforced on the
            # parsed `stops` count instead of being guessed at in the URL.
            unique = [
                fare
                for fare in unique
                if fare.stops is None or fare.stops <= query.max_stops
            ]
        unique.sort(key=lambda fare: fare.price)
        logger.info(
            "google_flights: %s parseable fares, %s after dedupe and stop filter",
            len(fares),
            len(unique),
        )
        if not unique:
            return ScrapeOutcome(site=self.site_name, status="no_results")
        return ScrapeOutcome(site=self.site_name, status="ok", fares=unique)

    async def _fetch_rows(self, context: BrowserContext, url: str) -> dict:
        await polite_delay(self._delay_min, self._delay_max)
        page = await context.new_page()
        try:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception as exc:
                raise RetryableScrapeError(f"navigation timeout/error: {exc}") from exc

            # Results stream in after load; wait for the first row rather than
            # a blind sleep, falling back to the settle wait if none appears.
            try:
                await page.locator(RESULT_ROW_SELECTOR).first.wait_for(
                    state="attached", timeout=SETTLE_WAIT_MS
                )
                await page.wait_for_timeout(1500)  # let the rest of the list fill in
            except Exception:  # noqa: BLE001 - absence of rows is a valid outcome
                await page.wait_for_timeout(SETTLE_WAIT_MS)

            return await page.evaluate(_EXTRACT_ROWS_JS, RESULT_ROW_SELECTOR)
        finally:
            await page.close()

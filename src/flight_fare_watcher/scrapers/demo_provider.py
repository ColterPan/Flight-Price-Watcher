"""An offline provider that returns synthetic fares.

This exists so the whole application - search, watches, alerts, price history,
the UI - can be exercised end to end with no API key, no network access and no
browser. Enable it with `ENABLED_SITES=demo`.

Its fares are **not real** and are labelled as such everywhere they surface:
`site` is `"demo"`, which the UI renders with a prominent "sample data" badge.
The numbers are derived deterministically from the query, so the same search
always returns the same fares (which makes price-drop behaviour testable) while
different routes return plausibly different ones.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

from playwright.async_api import BrowserContext

from flight_fare_watcher.models.fare import FareResult, Layover, ScrapeOutcome
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.base import FlightSiteAdapter

SITE_NAME = "demo"

#: (carrier code, display name, hub used for the connecting itineraries)
_CARRIERS: list[tuple[str, str, str]] = [
    ("AA", "American", "DFW"),
    ("DL", "Delta", "ATL"),
    ("UA", "United", "ORD"),
    ("B6", "JetBlue", "FLL"),
    ("AS", "Alaska", "SEA"),
    ("NK", "Spirit", "MCO"),
]

#: Multipliers applied to the base fare per cabin, roughly matching the real
#: spread observed on Google Flights (economy $294 -> business $1299).
_CABIN_MULTIPLIER: dict[str, Decimal] = {
    "economy": Decimal("1"),
    "premium_economy": Decimal("1.8"),
    "business": Decimal("4.4"),
    "first": Decimal("6.1"),
}

_BASE_PRICE_FLOOR = 89
_BASE_PRICE_SPREAD = 260
_FARES_PER_SEARCH = 8


def _clock(moment: datetime) -> str:
    """Format a time the way the Google Flights adapter reports it ("6:05 AM")."""
    return moment.strftime("%I:%M %p").lstrip("0")


def _seed(query: SearchQuery) -> int:
    """A stable integer derived from the route and dates."""
    raw = f"{query.origin}{query.destination}{query.depart_date}{query.return_date}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)


def build_demo_fares(query: SearchQuery, now: datetime | None = None) -> list[FareResult]:
    """Deterministic synthetic fares for `query`, cheapest first."""
    scraped_at = now or datetime.now()
    seed = _seed(query)
    base = Decimal(_BASE_PRICE_FLOOR + (seed % _BASE_PRICE_SPREAD))
    if query.is_round_trip:
        base *= Decimal("1.9")

    fares: list[FareResult] = []
    for index in range(_FARES_PER_SEARCH):
        carrier_code, airline, hub = _CARRIERS[(seed + index) % len(_CARRIERS)]
        stops = 0 if index % 3 != 2 else 1
        if query.max_stops is not None and stops > query.max_stops:
            continue

        price = base + Decimal(index * 23 + (seed >> (index + 1)) % 40)
        price = (price * _CABIN_MULTIPLIER[query.cabin] * query.adults).quantize(Decimal("1"))

        depart_hour = 6 + ((seed + index * 5) % 15)
        duration_minutes = 185 + stops * 160 + ((seed + index) % 70)
        depart_at = datetime.combine(query.depart_date, datetime.min.time()) + timedelta(
            hours=depart_hour, minutes=(seed + index * 7) % 60
        )
        arrive_at = depart_at + timedelta(minutes=duration_minutes)

        fares.append(
            FareResult(
                site=SITE_NAME,
                origin=query.origin,
                destination=query.destination,
                depart_date=query.depart_date,
                return_date=query.return_date,
                price=price,
                currency="USD",
                # A real search link for the same route, so the "open this
                # search" action still goes somewhere useful from demo data.
                deep_link=(
                    "https://www.google.com/travel/flights"
                    f"?q=Flights+from+{query.origin}+to+{query.destination}"
                ),
                scraped_at=scraped_at,
                airline=airline,
                carrier_code=carrier_code,
                trip_type="round_trip" if query.is_round_trip else "one_way",
                stops=stops,
                duration_minutes=duration_minutes,
                depart_time=_clock(depart_at),
                arrive_time=_clock(arrive_at),
                depart_at=depart_at,
                arrive_at=arrive_at,
                origin_airport_name=f"{query.origin} Airport",
                destination_airport_name=f"{query.destination} Airport",
                layovers=(
                    [Layover(airport=f"{hub} Airport", city=hub, duration_minutes=60 + index * 15)]
                    if stops
                    else []
                ),
                carry_on_bags_included=1,
                checked_bags_included=0 if carrier_code == "NK" else 1,
            )
        )

    fares.sort(key=lambda fare: fare.price)
    return fares


class DemoAdapter(FlightSiteAdapter):
    """Returns synthetic fares without touching the network or a browser."""

    site_name = SITE_NAME
    needs_browser = False

    def __init__(self, scrape_delay_min: float = 0.0, scrape_delay_max: float = 0.0) -> None:
        # Signature kept uniform with the other adapters so the registry can
        # build any provider the same way; delays are meaningless here.
        self._delay_min = scrape_delay_min
        self._delay_max = scrape_delay_max

    async def search(self, query: SearchQuery, context: BrowserContext | None) -> ScrapeOutcome:
        fares = build_demo_fares(query)
        if not fares:
            return ScrapeOutcome(site=self.site_name, status="no_results")
        return ScrapeOutcome(
            site=self.site_name,
            status="ok",
            fares=fares,
            diagnostic="sample data - not real fares",
        )

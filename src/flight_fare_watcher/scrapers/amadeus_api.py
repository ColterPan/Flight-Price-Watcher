"""Amadeus Self-Service Flight Offers Search provider.

An API-backed alternative to scraping. Where the Google Flights adapter reads
a rendered page, this calls a documented, paid-for-by-the-request API that
returns structured itineraries - so it does not break when a page changes, and
using it does not conflict with anyone's Terms of Service.

Setup (free): create an app at https://developers.amadeus.com, then put the
key and secret in `.env` as `AMADEUS_API_KEY` / `AMADEUS_API_SECRET` and add
`amadeus` to `ENABLED_SITES`.

Two things to know about the free tier:

* It defaults to the **test** host, whose fares come from a cached snapshot
  rather than live inventory, so prices will not match what an airline is
  selling today. Point `AMADEUS_HOSTNAME` at `api.amadeus.com` once you have
  production access.
* It has no booking URL in its response, so `deep_link` is a Google Flights
  search for the same route - honest about being a search link rather than a
  per-fare purchase link.

When no credentials are configured this provider reports `not_configured`
rather than `error`: a missing optional integration is not a failure, and the
UI says so differently.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx
from playwright.async_api import BrowserContext

from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import FareResult, Layover, ScrapeOutcome
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.base import FlightSiteAdapter

logger = get_logger(__name__)

SITE_NAME = "amadeus"

TEST_HOSTNAME = "test.api.amadeus.com"
PRODUCTION_HOSTNAME = "api.amadeus.com"

REQUEST_TIMEOUT_SECONDS = 25.0
MAX_OFFERS = 20
#: Refresh the OAuth token this many seconds before it actually expires.
TOKEN_EXPIRY_MARGIN_SECONDS = 60

_TRAVEL_CLASSES: dict[str, str] = {
    "economy": "ECONOMY",
    "premium_economy": "PREMIUM_ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}

_ISO_DURATION_RE = re.compile(r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?$")


def parse_iso_duration(value: str | None) -> int | None:
    """Convert an ISO-8601 duration ("PT6H22M", "P1DT2H") to total minutes."""
    if not value:
        return None
    match = _ISO_DURATION_RE.match(value.strip())
    if match is None:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    total = days * 1440 + hours * 60 + minutes
    return total or None


def _parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _clock(moment: datetime | None) -> str | None:
    return moment.strftime("%I:%M %p").lstrip("0") if moment else None


def _google_search_link(query: SearchQuery) -> str:
    """A Google Flights search for the same route, used as the fallback link."""
    trip = (
        f"{query.depart_date.isoformat()} through {query.return_date.isoformat()}"
        if query.return_date
        else f"{query.depart_date.isoformat()} one way"
    )
    text = f"Flights from {query.origin} to {query.destination} on {trip}"
    return f"https://www.google.com/travel/flights?q={quote(text)}&hl=en&gl=US&curr=USD"


def parse_offer(
    offer: dict,
    carriers: dict[str, str],
    query: SearchQuery,
    deep_link: str,
    scraped_at: datetime,
) -> FareResult | None:
    """Convert one Amadeus flight offer into a `FareResult`.

    Returns `None` for an offer we cannot price or that has no outbound
    itinerary, so one malformed entry does not discard the whole response.
    """
    try:
        total = offer["price"]["grandTotal"]
        currency = offer["price"].get("currency") or "USD"
        itineraries = offer["itineraries"]
        segments = itineraries[0]["segments"]
        if not segments:
            return None
    except (KeyError, IndexError, TypeError):
        return None

    try:
        price = Decimal(str(total))
    except InvalidOperation:
        return None
    if price <= 0:
        return None

    first_segment = segments[0]
    last_segment = segments[-1]
    depart_at = _parse_moment(first_segment.get("departure", {}).get("at"))
    arrive_at = _parse_moment(last_segment.get("arrival", {}).get("at"))

    carrier_codes = {segment.get("carrierCode") for segment in segments if segment.get("carrierCode")}
    carrier_code = first_segment.get("carrierCode")
    airline_names = [carriers.get(code, code).title() for code in sorted(carrier_codes)]

    layovers: list[Layover] = []
    for previous, following in zip(segments, segments[1:]):
        airport = previous.get("arrival", {}).get("iataCode")
        if not airport:
            continue
        gap = None
        landed = _parse_moment(previous.get("arrival", {}).get("at"))
        departed = _parse_moment(following.get("departure", {}).get("at"))
        if landed and departed:
            gap = max(int((departed - landed).total_seconds() // 60), 0)
        layovers.append(Layover(airport=airport, city=airport, duration_minutes=gap))

    return FareResult(
        site=SITE_NAME,
        origin=query.origin,
        destination=query.destination,
        depart_date=query.depart_date,
        return_date=query.return_date,
        price=price,
        currency=currency,
        deep_link=deep_link,
        scraped_at=scraped_at,
        airline=" and ".join(airline_names) or None,
        carrier_code=carrier_code,
        trip_type="round_trip" if len(itineraries) > 1 else "one_way",
        stops=max(len(segments) - 1, 0),
        duration_minutes=parse_iso_duration(itineraries[0].get("duration")),
        depart_time=_clock(depart_at),
        arrive_time=_clock(arrive_at),
        depart_at=depart_at,
        arrive_at=arrive_at,
        origin_airport_name=first_segment.get("departure", {}).get("iataCode"),
        destination_airport_name=last_segment.get("arrival", {}).get("iataCode"),
        layovers=layovers,
    )


class AmadeusAdapter(FlightSiteAdapter):
    site_name = SITE_NAME
    needs_browser = False

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        hostname: str = TEST_HOSTNAME,
        scrape_delay_min: float = 0.0,
        scrape_delay_max: float = 0.0,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._hostname = hostname or TEST_HOSTNAME
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_secret)

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        """Fetch (and cache until shortly before expiry) an OAuth token."""
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        response = await client.post(
            f"https://{self._hostname}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._api_key,
                "client_secret": self._api_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ValueError("Amadeus token response contained no access_token")
        expires_in = float(payload.get("expires_in") or 0)
        self._token = token
        self._token_expires_at = time.monotonic() + max(
            expires_in - TOKEN_EXPIRY_MARGIN_SECONDS, 0
        )
        return token

    def _search_params(self, query: SearchQuery) -> dict:
        params = {
            "originLocationCode": query.origin,
            "destinationLocationCode": query.destination,
            "departureDate": query.depart_date.isoformat(),
            "adults": query.adults,
            "travelClass": _TRAVEL_CLASSES[query.cabin],
            "currencyCode": "USD",
            "max": MAX_OFFERS,
        }
        if query.return_date:
            params["returnDate"] = query.return_date.isoformat()
        if query.max_stops == 0:
            params["nonStop"] = "true"
        return params

    async def search(self, query: SearchQuery, context: BrowserContext | None) -> ScrapeOutcome:
        if not self.is_configured:
            return ScrapeOutcome(
                site=self.site_name,
                status="not_configured",
                diagnostic=(
                    "set AMADEUS_API_KEY and AMADEUS_API_SECRET in .env to enable "
                    "the Amadeus provider"
                ),
            )

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                token = await self._access_token(client)
                response = await client.get(
                    f"https://{self._hostname}/v2/shopping/flight-offers",
                    params=self._search_params(query),
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code == 401:
                    # Token rejected - drop the cache so the next run re-auths.
                    self._token = None
                    return ScrapeOutcome(
                        site=self.site_name,
                        status="error",
                        diagnostic="Amadeus rejected the credentials (401)",
                    )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = self._error_detail(exc.response)
            logger.warning("amadeus: HTTP %s: %s", exc.response.status_code, detail)
            return ScrapeOutcome(
                site=self.site_name,
                status="error",
                diagnostic=f"HTTP {exc.response.status_code}: {detail}",
            )
        except Exception as exc:  # noqa: BLE001 - adapter must never propagate
            logger.exception("amadeus: unexpected error")
            return ScrapeOutcome(site=self.site_name, status="error", diagnostic=str(exc))

        return self._build_outcome(payload, query)

    def _build_outcome(self, payload: dict, query: SearchQuery) -> ScrapeOutcome:
        offers = payload.get("data") or []
        if not offers:
            return ScrapeOutcome(site=self.site_name, status="no_results")

        carriers = (payload.get("dictionaries") or {}).get("carriers") or {}
        deep_link = _google_search_link(query)
        scraped_at = datetime.now()

        fares = [
            fare
            for fare in (
                parse_offer(offer, carriers, query, deep_link, scraped_at) for offer in offers
            )
            if fare is not None
        ]
        if query.max_stops is not None:
            fares = [
                fare for fare in fares if fare.stops is None or fare.stops <= query.max_stops
            ]

        if not fares:
            return ScrapeOutcome(
                site=self.site_name,
                status="no_results",
                diagnostic=f"{len(offers)} offers returned but none were usable",
            )

        fares.sort(key=lambda fare: fare.price)
        logger.info("amadeus: %s offers -> %s fares", len(offers), len(fares))
        return ScrapeOutcome(site=self.site_name, status="ok", fares=fares)

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Pull Amadeus's own error text out of a failed response."""
        try:
            errors = response.json().get("errors") or []
        except Exception:  # noqa: BLE001 - non-JSON error body
            return response.text[:200]
        if not errors:
            return response.text[:200]
        first = errors[0]
        return f"{first.get('title', '')} {first.get('detail', '')}".strip()

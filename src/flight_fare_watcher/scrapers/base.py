"""Shared Playwright helpers and the adapter interface every provider implements.

"Provider" covers both kinds of fare source:

* **Browser adapters** (`google_flights.py`) drive a real page with Playwright.
* **API adapters** (`amadeus_api.py`, `demo_provider.py`) call an HTTP API or
  return canned data and ignore the `BrowserContext` they are handed.

Both satisfy the same `FlightSiteAdapter` contract, so the orchestrator, the
registry and the scheduler do not care which kind they are talking to. The
package is still called `scrapers` for historical reasons; the contract itself
is source-agnostic.
"""

from __future__ import annotations

import abc
import asyncio
import random
from typing import Awaitable, Callable, TypeVar

from playwright.async_api import Browser, BrowserContext

from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome
from flight_fare_watcher.models.search import SearchQuery

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

T = TypeVar("T")


async def new_context(browser: Browser) -> BrowserContext:
    """A browser context with a realistic desktop footprint.

    This is deliberately NOT proxy rotation or fingerprint evasion - just
    enough to avoid looking like an obviously headless/default automation
    profile. See docs/recon_notes.md and the README's ToS disclaimer.
    """
    return await browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=DESKTOP_USER_AGENT,
        locale="en-US",
        timezone_id="America/New_York",
    )


async def polite_delay(min_seconds: float, max_seconds: float) -> None:
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))


class RetryableScrapeError(Exception):
    """Transient failure (timeout, nav hiccup) worth retrying."""


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    max_attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> T:
    last_exc: RetryableScrapeError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except RetryableScrapeError as exc:
            last_exc = exc
            if attempt < max_attempts:
                await asyncio.sleep(backoff_seconds * attempt)
    assert last_exc is not None
    raise last_exc


class FlightSiteAdapter(abc.ABC):
    """One adapter per fare source. Must never let an exception escape `search`."""

    site_name: str

    #: Whether this provider needs the shared Playwright browser. API adapters
    #: set this to False so the orchestrator can skip building a context for
    #: them - and skip launching a browser at all when no provider needs one.
    needs_browser: bool = True

    @abc.abstractmethod
    async def search(self, query: SearchQuery, context: BrowserContext | None) -> ScrapeOutcome:
        """Find fares for `query`. Returns a `ScrapeOutcome`, never raises."""
        raise NotImplementedError

    async def resolve_booking_url(
        self,
        query: SearchQuery,
        fare: FareResult,
        context: BrowserContext | None,
    ) -> str | None:
        """Resolve a link to this specific itinerary's purchase page, if possible.

        The default is `None`, meaning "this provider has no per-fare link
        beyond the `deep_link` already on the fare". Returning `None` is always
        acceptable and must never raise - a missing booking link degrades the
        UI to a search link, it does not fail the search.
        """
        return None

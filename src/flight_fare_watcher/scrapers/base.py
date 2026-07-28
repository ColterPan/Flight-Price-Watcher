"""Shared Playwright helpers and the adapter interface every scraper implements."""

from __future__ import annotations

import abc
import asyncio
import random
from datetime import date
from typing import Awaitable, Callable, TypeVar

from playwright.async_api import Browser, BrowserContext

from flight_fare_watcher.models.fare import ScrapeOutcome

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
    """One adapter per scraped site. Must never let an exception escape `search`."""

    site_name: str

    @abc.abstractmethod
    async def search(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date | None,
        context: BrowserContext,
    ) -> ScrapeOutcome:
        raise NotImplementedError

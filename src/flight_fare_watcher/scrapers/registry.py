"""Maps configured provider names to adapter instances.

A provider can be enabled or disabled through the `ENABLED_SITES` env var with
no code change - which is the documented response to a scraper starting to get
blocked (see docs/recon_notes.md).
"""

from __future__ import annotations

from flight_fare_watcher.config import Settings
from flight_fare_watcher.scrapers.amadeus_api import AmadeusAdapter
from flight_fare_watcher.scrapers.base import FlightSiteAdapter
from flight_fare_watcher.scrapers.demo_provider import DemoAdapter
from flight_fare_watcher.scrapers.google_flights import GoogleFlightsAdapter

#: Every provider this build knows how to construct.
KNOWN_SITES: tuple[str, ...] = ("google_flights", "amadeus", "demo")

#: One-line description per provider, surfaced in the UI so the source of a
#: fare is never ambiguous.
SITE_DESCRIPTIONS: dict[str, str] = {
    "google_flights": "Live prices scraped from Google Flights",
    "amadeus": "Amadeus Self-Service flight offers API",
    "demo": "Sample data - not real fares",
}


def build_enabled_adapters(
    enabled_site_names: list[str],
    settings: Settings | None = None,
    scrape_delay_min: float = 1.5,
    scrape_delay_max: float = 4.0,
) -> list[FlightSiteAdapter]:
    """Instantiate the named providers.

    `settings` supplies provider credentials; it is optional so tests can build
    the browser-only adapters without a full settings object.
    """
    adapters: list[FlightSiteAdapter] = []
    for name in enabled_site_names:
        if name == "google_flights":
            adapters.append(
                GoogleFlightsAdapter(
                    scrape_delay_min=scrape_delay_min,
                    scrape_delay_max=scrape_delay_max,
                )
            )
        elif name == "amadeus":
            adapters.append(
                AmadeusAdapter(
                    api_key=settings.amadeus_api_key if settings else "",
                    api_secret=settings.amadeus_api_secret if settings else "",
                    hostname=settings.amadeus_hostname if settings else "",
                )
            )
        elif name == "demo":
            adapters.append(DemoAdapter())
        else:
            raise ValueError(
                f"Unknown site adapter {name!r}. Known adapters: {sorted(KNOWN_SITES)}"
            )
    return adapters


def build_adapters_from_settings(settings: Settings) -> list[FlightSiteAdapter]:
    """The providers this configuration has enabled."""
    return build_enabled_adapters(
        settings.enabled_site_list,
        settings=settings,
        scrape_delay_min=settings.scrape_delay_min_seconds,
        scrape_delay_max=settings.scrape_delay_max_seconds,
    )

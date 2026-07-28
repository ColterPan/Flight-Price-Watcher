"""Maps configured site names to adapter instances.

A site can be disabled instantly via the ENABLED_SITES env var, with no code
change, if it starts getting reliably blocked (see docs/recon_notes.md).
"""

from __future__ import annotations

from flight_fare_watcher.scrapers.base import FlightSiteAdapter
from flight_fare_watcher.scrapers.google_flights import GoogleFlightsAdapter

_ADAPTER_CLASSES: dict[str, type[FlightSiteAdapter]] = {
    "google_flights": GoogleFlightsAdapter,
}


def build_enabled_adapters(
    enabled_site_names: list[str],
    scrape_delay_min: float = 1.5,
    scrape_delay_max: float = 4.0,
) -> list[FlightSiteAdapter]:
    adapters = []
    for name in enabled_site_names:
        adapter_cls = _ADAPTER_CLASSES.get(name)
        if adapter_cls is None:
            raise ValueError(f"Unknown site adapter '{name}'. Known adapters: {sorted(_ADAPTER_CLASSES)}")
        adapters.append(adapter_cls(scrape_delay_min=scrape_delay_min, scrape_delay_max=scrape_delay_max))
    return adapters

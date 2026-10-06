"""Application configuration, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- email alerts ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    alert_from_email: str = ""
    alert_to_email: str = ""

    # --- storage ---
    database_path: str = "data/fares.db"

    # --- providers ---
    enabled_sites: str = "google_flights"
    scrape_delay_min_seconds: float = 1.5
    scrape_delay_max_seconds: float = 4.0
    playwright_headless: bool = True

    #: Amadeus Self-Service credentials. Empty means the provider reports
    #: `not_configured` instead of failing. See scrapers/amadeus_api.py.
    amadeus_api_key: str = ""
    amadeus_api_secret: str = ""
    amadeus_hostname: str = "test.api.amadeus.com"

    # --- booking links ---
    #: How many of the cheapest fares get a per-flight booking link resolved
    #: during a search. Each costs an extra page load and click (~8s measured),
    #: so this trades search latency for immediately-clickable booking links.
    #: 0 disables it; any row can still be resolved on demand from the UI.
    booking_link_resolve_count: int = Field(default=1, ge=0, le=5)

    # --- search result cache ---
    #: Repeating an identical search within this window reuses the previous
    #: result instead of re-scraping. Keeps the UI responsive while iterating
    #: on filters, and avoids hammering the source. 0 disables the cache.
    search_cache_ttl_seconds: float = Field(default=300.0, ge=0)

    # --- currency conversion ---
    #: Every fare provider prices in USD (see currency.py) - this only
    #: controls which currency the UI shows by default; the user can switch
    #: it from the results page without re-searching.
    default_display_currency: str = "USD"
    #: How long a fetched rate snapshot is treated as fresh before refetching.
    #: Frankfurter/ECB rates update roughly once per weekday, so this is
    #: about keeping the app responsive, not chasing intraday movement.
    exchange_rate_cache_ttl_seconds: float = Field(default=3600.0, ge=0)

    # --- watch scheduler ---
    check_interval_hours: float = Field(default=4.0, gt=0)

    @property
    def enabled_site_list(self) -> list[str]:
        return [site.strip() for site in self.enabled_sites.split(",") if site.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

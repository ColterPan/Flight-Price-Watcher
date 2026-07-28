"""Application configuration, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    alert_from_email: str = ""
    alert_to_email: str = ""

    database_path: str = "data/fares.db"

    enabled_sites: str = "google_flights"
    scrape_delay_min_seconds: float = 1.5
    scrape_delay_max_seconds: float = 4.0
    playwright_headless: bool = True

    check_interval_hours: float = Field(default=4.0, gt=0)

    @property
    def enabled_site_list(self) -> list[str]:
        return [s.strip() for s in self.enabled_sites.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

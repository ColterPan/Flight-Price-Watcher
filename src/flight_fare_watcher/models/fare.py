"""Core data types for a single scraped fare and the outcome of a scrape attempt."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ScrapeStatus = Literal["ok", "no_results", "blocked_or_structure_changed", "error"]


class FareResult(BaseModel):
    site: str
    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None
    price: Decimal
    currency: str
    deep_link: str
    scraped_at: datetime
    airline: str | None = None

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("price must be positive")
        return value

    @field_validator("currency")
    @classmethod
    def currency_must_be_present(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("currency must not be empty")
        return value.strip().upper()


class ScrapeOutcome(BaseModel):
    site: str
    status: ScrapeStatus
    fares: list[FareResult] = Field(default_factory=list)
    diagnostic: str | None = None

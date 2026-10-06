"""Core data types for a single scraped/fetched fare and the outcome of a provider attempt."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ScrapeStatus = Literal[
    "ok",
    "no_results",
    "blocked_or_structure_changed",
    "not_configured",
    "error",
]

TripType = Literal["one_way", "round_trip"]

#: Statuses that mean "this provider did its job" - used by the UI and by the
#: scheduler to decide whether a route genuinely has no fares or is just broken.
HEALTHY_STATUSES: frozenset[str] = frozenset({"ok", "no_results"})


class Layover(BaseModel):
    """One stop in an itinerary, as described by the source."""

    airport: str
    city: str | None = None
    duration_minutes: int | None = None


class FareResult(BaseModel):
    """One bookable itinerary at one price, from one provider.

    Everything past `airline` is optional: a provider that cannot supply a
    field leaves it `None` rather than inventing a value, and the UI degrades
    to showing only what was actually observed.
    """

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

    # --- itinerary detail (needed to actually choose a flight) ---
    carrier_code: str | None = None
    trip_type: TripType | None = None
    stops: int | None = None
    duration_minutes: int | None = None
    depart_time: str | None = None
    arrive_time: str | None = None
    depart_at: datetime | None = None
    arrive_at: datetime | None = None
    origin_airport_name: str | None = None
    destination_airport_name: str | None = None
    layovers: list[Layover] = Field(default_factory=list)
    operated_by: str | None = None
    carry_on_bags_included: int | None = None
    checked_bags_included: int | None = None

    #: A link to the specific flight's purchase page, when the provider could
    #: resolve one. `deep_link` is always set but may only be a search page;
    #: `booking_url` is only set when it points at this itinerary.
    booking_url: str | None = None

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

    @property
    def best_link(self) -> str:
        """The most specific link available for this fare."""
        return self.booking_url or self.deep_link

    def itinerary_key(self) -> tuple:
        """Identity of the *itinerary*, used to drop duplicate rows.

        Google Flights renders the same flight in both its "Best flights" and
        "All flights" lists, so the same itinerary legitimately appears twice
        in one scrape. Price is part of the key because the same flight at two
        different fares is two different offers.
        """
        return (
            self.site,
            self.carrier_code or self.airline,
            self.depart_time,
            self.arrive_time,
            self.duration_minutes,
            self.stops,
            self.price,
        )


class ScrapeOutcome(BaseModel):
    site: str
    status: ScrapeStatus
    fares: list[FareResult] = Field(default_factory=list)
    diagnostic: str | None = None

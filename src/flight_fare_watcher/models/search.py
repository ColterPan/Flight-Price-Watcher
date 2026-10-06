"""The validated description of one flight search.

Every provider receives a `SearchQuery` rather than loose arguments, so adding
a search option (cabin, passengers, stop limit) does not change the signature
of every adapter.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CabinClass = Literal["economy", "premium_economy", "business", "first"]

_IATA_RE = re.compile(r"^[A-Z]{3}$")

#: Google will happily return fares years out, but a date that far away is
#: almost always a typo (wrong year), and schedules are not published yet.
MAX_SEARCH_HORIZON_DAYS = 365

CABIN_LABELS: dict[str, str] = {
    "economy": "Economy",
    "premium_economy": "Premium economy",
    "business": "Business",
    "first": "First",
}


class SearchQuery(BaseModel):
    """One route + dates + traveller options, validated at the API boundary."""

    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None
    adults: int = Field(default=1, ge=1, le=9)
    cabin: CabinClass = "economy"
    #: `None` means "any number of stops". 0 means nonstop only.
    max_stops: int | None = Field(default=None, ge=0, le=3)

    @model_validator(mode="after")
    def validate_query(self) -> SearchQuery:
        self._normalize_airports()
        self._validate_dates()
        return self

    def _normalize_airports(self) -> None:
        for field in ("origin", "destination"):
            code = (getattr(self, field) or "").strip().upper()
            if not _IATA_RE.match(code):
                raise ValueError(
                    f"{field} must be a 3-letter IATA airport code (e.g. JFK), got {code!r}"
                )
            setattr(self, field, code)

        if self.origin == self.destination:
            raise ValueError("origin and destination must be different airports")

    def _validate_dates(self) -> None:
        today = date.today()
        if self.depart_date < today:
            raise ValueError(f"depart_date {self.depart_date} is in the past")
        if (self.depart_date - today).days > MAX_SEARCH_HORIZON_DAYS:
            raise ValueError(
                f"depart_date {self.depart_date} is more than "
                f"{MAX_SEARCH_HORIZON_DAYS} days away - check the year"
            )
        if self.return_date is not None and self.return_date < self.depart_date:
            raise ValueError(
                f"return_date {self.return_date} is before depart_date {self.depart_date}"
            )

    @property
    def is_round_trip(self) -> bool:
        return self.return_date is not None

    @property
    def route_label(self) -> str:
        return f"{self.origin}-{self.destination}"

    def cache_key(self) -> tuple:
        """Identity of this search, for the short-lived result cache."""
        return (
            self.origin,
            self.destination,
            self.depart_date,
            self.return_date,
            self.adults,
            self.cabin,
            self.max_stops,
        )

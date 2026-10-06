"""Data types for a saved, periodically re-checked route."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

from flight_fare_watcher.models.search import CabinClass, SearchQuery


class WatchedRouteCreate(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None
    target_price: Decimal | None = Field(default=None, gt=0)
    currency: str = "USD"
    alert_email: EmailStr | None = None

    #: Re-checks use these, so the watch keeps comparing like with like.
    adults: int = Field(default=1, ge=1, le=9)
    cabin: CabinClass = "economy"
    max_stops: int | None = Field(default=None, ge=0, le=3)

    @model_validator(mode="after")
    def validate_route(self) -> WatchedRouteCreate:
        # Reuse the search validation so a watch cannot be saved for a route or
        # date range that could never be searched.
        query = self.to_query()
        self.origin = query.origin
        self.destination = query.destination
        return self

    def to_query(self) -> SearchQuery:
        """The search this watch re-runs on every check."""
        return SearchQuery(
            origin=self.origin,
            destination=self.destination,
            depart_date=self.depart_date,
            return_date=self.return_date,
            adults=self.adults,
            cabin=self.cabin,
            max_stops=self.max_stops,
        )


class WatchedRoute(WatchedRouteCreate):
    id: int
    is_active: bool = True
    created_at: datetime

    #: Outcome of the most recent background check.
    last_checked_at: datetime | None = None
    last_status: str | None = None
    last_price: Decimal | None = None

    @model_validator(mode="after")
    def validate_route(self) -> WatchedRoute:
        # A stored watch is not re-validated against today's date: a watch
        # whose departure has passed must still be readable and deletable,
        # which the create-time date checks would forbid.
        return self

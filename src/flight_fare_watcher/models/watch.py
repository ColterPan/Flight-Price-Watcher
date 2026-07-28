"""Data types for a saved, periodically re-checked route."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class WatchedRouteCreate(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None
    target_price: Decimal | None = None
    currency: str = "USD"
    alert_email: str | None = None


class WatchedRoute(WatchedRouteCreate):
    id: int
    is_active: bool = True
    created_at: datetime

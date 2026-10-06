"""Shared test helpers."""

from __future__ import annotations

from datetime import date, timedelta


def future_date(days_ahead: int = 60) -> date:
    """A date far enough ahead to pass `SearchQuery`'s "not in the past" check.

    Tests need a *valid* future date rather than a literal one, since a
    hardcoded date eventually lands in the past as real time passes it by.
    """
    return date.today() + timedelta(days=days_ahead)

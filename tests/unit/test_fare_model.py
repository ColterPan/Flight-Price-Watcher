from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome


def _base_kwargs(**overrides):
    kwargs = dict(
        site="google_flights",
        origin="JFK",
        destination="LAX",
        depart_date=date(2026, 9, 1),
        return_date=None,
        price=Decimal("189.00"),
        currency="usd",
        deep_link="https://example.com/search",
        scraped_at=datetime(2026, 7, 28, 12, 0, 0),
        airline="JetBlue",
    )
    kwargs.update(overrides)
    return kwargs


def test_fare_result_normalizes_currency_to_uppercase():
    fare = FareResult(**_base_kwargs())
    assert fare.currency == "USD"


def test_fare_result_rejects_negative_price():
    with pytest.raises(ValidationError):
        FareResult(**_base_kwargs(price=Decimal("-10")))


def test_fare_result_rejects_zero_price():
    with pytest.raises(ValidationError):
        FareResult(**_base_kwargs(price=Decimal("0")))


def test_fare_result_rejects_empty_currency():
    with pytest.raises(ValidationError):
        FareResult(**_base_kwargs(currency="   "))


def test_scrape_outcome_defaults_to_empty_fare_list():
    outcome = ScrapeOutcome(site="google_flights", status="no_results")
    assert outcome.fares == []
    assert outcome.diagnostic is None


def test_scrape_outcome_distinguishes_no_results_from_blocked():
    no_results = ScrapeOutcome(site="google_flights", status="no_results")
    blocked = ScrapeOutcome(site="google_flights", status="blocked_or_structure_changed", diagnostic="no rows found")
    assert no_results.status != blocked.status

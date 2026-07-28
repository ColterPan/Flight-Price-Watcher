from datetime import date, datetime
from decimal import Decimal

import pytest

from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome
from flight_fare_watcher.scrapers.base import FlightSiteAdapter
from flight_fare_watcher.search.orchestrator import _run_one_adapter, build_response


def _fare(site: str, price: str) -> FareResult:
    return FareResult(
        site=site,
        origin="JFK",
        destination="LAX",
        depart_date=date(2026, 9, 1),
        return_date=None,
        price=Decimal(price),
        currency="USD",
        deep_link="https://example.com",
        scraped_at=datetime(2026, 7, 28, 12, 0, 0),
        airline="Test Air",
    )


def test_build_response_sorts_fares_ascending_by_price():
    outcomes = [
        ScrapeOutcome(site="site_a", status="ok", fares=[_fare("site_a", "300")]),
        ScrapeOutcome(site="site_b", status="ok", fares=[_fare("site_b", "150"), _fare("site_b", "500")]),
    ]
    response = build_response("JFK", "LAX", date(2026, 9, 1), None, outcomes)
    assert [str(f.price) for f in response.fares] == ["150", "300", "500"]


def test_build_response_includes_per_site_status_even_when_some_sites_fail():
    outcomes = [
        ScrapeOutcome(site="google_flights", status="ok", fares=[_fare("google_flights", "200")]),
        ScrapeOutcome(site="kiwi", status="blocked_or_structure_changed", diagnostic="captcha"),
    ]
    response = build_response("JFK", "LAX", date(2026, 9, 1), None, outcomes)
    assert response.site_statuses == {"google_flights": "ok", "kiwi": "blocked_or_structure_changed"}
    assert len(response.fares) == 1


def test_build_response_handles_no_adapters_enabled():
    response = build_response("JFK", "LAX", date(2026, 9, 1), None, [])
    assert response.fares == []
    assert response.site_statuses == {}


class _CrashingAdapter(FlightSiteAdapter):
    site_name = "crashing_site"

    async def search(self, origin, destination, depart_date, return_date, context):
        raise RuntimeError("simulated adapter bug")


class _WorkingAdapter(FlightSiteAdapter):
    site_name = "working_site"

    async def search(self, origin, destination, depart_date, return_date, context):
        return ScrapeOutcome(site=self.site_name, status="ok", fares=[_fare(self.site_name, "199")])


@pytest.mark.asyncio
async def test_run_one_adapter_converts_unexpected_exception_to_error_outcome():
    outcome = await _run_one_adapter(_CrashingAdapter(), None, "JFK", "LAX", date(2026, 9, 1), None)
    assert outcome.status == "error"
    assert outcome.site == "crashing_site"
    assert "simulated adapter bug" in outcome.diagnostic


@pytest.mark.asyncio
async def test_run_one_adapter_passes_through_successful_outcome():
    outcome = await _run_one_adapter(_WorkingAdapter(), None, "JFK", "LAX", date(2026, 9, 1), None)
    assert outcome.status == "ok"
    assert len(outcome.fares) == 1

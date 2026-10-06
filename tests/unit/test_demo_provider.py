import pytest

from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.demo_provider import DemoAdapter, build_demo_fares

from ..conftest import future_date


def _query(**overrides) -> SearchQuery:
    defaults = dict(origin="JFK", destination="LAX", depart_date=future_date())
    defaults.update(overrides)
    return SearchQuery(**defaults)


def test_build_demo_fares_returns_sorted_nonempty_list():
    fares = build_demo_fares(_query())
    assert len(fares) > 0
    assert all(fares[i].price <= fares[i + 1].price for i in range(len(fares) - 1))


def test_build_demo_fares_is_deterministic_for_the_same_query():
    first = build_demo_fares(_query())
    second = build_demo_fares(_query())
    assert [str(f.price) for f in first] == [str(f.price) for f in second]


def test_build_demo_fares_differs_between_routes():
    jfk_lax = build_demo_fares(_query())
    sfo_ord = build_demo_fares(_query(origin="SFO", destination="ORD"))
    assert [str(f.price) for f in jfk_lax] != [str(f.price) for f in sfo_ord]


def test_build_demo_fares_scales_with_passenger_count():
    one_adult = build_demo_fares(_query(adults=1))
    two_adults = build_demo_fares(_query(adults=2))
    assert two_adults[0].price > one_adult[0].price


def test_build_demo_fares_scales_with_cabin():
    economy = build_demo_fares(_query(cabin="economy"))
    business = build_demo_fares(_query(cabin="business"))
    assert business[0].price > economy[0].price


def test_build_demo_fares_respects_max_stops_filter():
    fares = build_demo_fares(_query(max_stops=0))
    assert all(fare.stops == 0 for fare in fares)


def test_build_demo_fares_all_fares_are_tagged_as_demo_site():
    for fare in build_demo_fares(_query()):
        assert fare.site == "demo"


@pytest.mark.asyncio
async def test_demo_adapter_search_returns_ok_outcome_with_diagnostic_label():
    adapter = DemoAdapter()
    outcome = await adapter.search(_query(), context=None)
    assert outcome.status == "ok"
    assert len(outcome.fares) > 0
    assert "sample" in (outcome.diagnostic or "").lower()


def test_demo_adapter_does_not_need_a_browser():
    assert DemoAdapter().needs_browser is False

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from flight_fare_watcher.models.search import MAX_SEARCH_HORIZON_DAYS, SearchQuery

from ..conftest import future_date


def test_normalizes_lowercase_airport_codes():
    query = SearchQuery(origin="jfk", destination="lax", depart_date=future_date())
    assert query.origin == "JFK"
    assert query.destination == "LAX"


def test_rejects_non_iata_origin_code():
    with pytest.raises(ValidationError, match="IATA"):
        SearchQuery(origin="NEWYORK", destination="LAX", depart_date=future_date())


def test_rejects_origin_equal_to_destination():
    with pytest.raises(ValidationError, match="different airports"):
        SearchQuery(origin="JFK", destination="JFK", depart_date=future_date())


def test_rejects_depart_date_in_the_past():
    with pytest.raises(ValidationError, match="in the past"):
        SearchQuery(origin="JFK", destination="LAX", depart_date=date(2000, 1, 1))


def test_rejects_depart_date_far_beyond_the_search_horizon():
    too_far = date.today() + timedelta(days=MAX_SEARCH_HORIZON_DAYS + 30)
    with pytest.raises(ValidationError, match="year"):
        SearchQuery(origin="JFK", destination="LAX", depart_date=too_far)


def test_accepts_depart_date_at_exactly_today():
    query = SearchQuery(origin="JFK", destination="LAX", depart_date=date.today())
    assert query.depart_date == date.today()


def test_rejects_return_date_before_depart_date():
    depart = future_date(30)
    earlier_return = future_date(10)
    with pytest.raises(ValidationError, match="before depart_date"):
        SearchQuery(origin="JFK", destination="LAX", depart_date=depart, return_date=earlier_return)


def test_accepts_return_date_equal_to_depart_date():
    depart = future_date()
    query = SearchQuery(origin="JFK", destination="LAX", depart_date=depart, return_date=depart)
    assert query.is_round_trip is True


def test_is_round_trip_reflects_presence_of_return_date():
    one_way = SearchQuery(origin="JFK", destination="LAX", depart_date=future_date())
    round_trip = SearchQuery(
        origin="JFK", destination="LAX", depart_date=future_date(30), return_date=future_date(37)
    )
    assert one_way.is_round_trip is False
    assert round_trip.is_round_trip is True


def test_route_label():
    query = SearchQuery(origin="JFK", destination="LAX", depart_date=future_date())
    assert query.route_label == "JFK-LAX"


def test_cache_key_differs_when_any_search_option_differs():
    base = SearchQuery(origin="JFK", destination="LAX", depart_date=future_date())
    more_adults = SearchQuery(origin="JFK", destination="LAX", depart_date=future_date(), adults=2)
    different_cabin = SearchQuery(
        origin="JFK", destination="LAX", depart_date=future_date(), cabin="business"
    )

    assert base.cache_key() != more_adults.cache_key()
    assert base.cache_key() != different_cabin.cache_key()


def test_cache_key_is_identical_for_equivalent_queries():
    depart = future_date()
    first = SearchQuery(origin="JFK", destination="LAX", depart_date=depart)
    second = SearchQuery(origin="JFK", destination="LAX", depart_date=depart)
    assert first.cache_key() == second.cache_key()


@pytest.mark.parametrize("adults", [0, 10])
def test_rejects_adults_outside_allowed_range(adults):
    with pytest.raises(ValidationError):
        SearchQuery(origin="JFK", destination="LAX", depart_date=future_date(), adults=adults)


@pytest.mark.parametrize("max_stops", [-1, 4])
def test_rejects_max_stops_outside_allowed_range(max_stops):
    with pytest.raises(ValidationError):
        SearchQuery(origin="JFK", destination="LAX", depart_date=future_date(), max_stops=max_stops)

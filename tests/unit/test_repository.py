from datetime import date, datetime
from decimal import Decimal

import pytest

from flight_fare_watcher.db import database, repository
from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.watch import WatchedRouteCreate


@pytest.fixture
def conn():
    connection = database.connect(":memory:")
    yield connection
    connection.close()


def _make_fare(price: str, **overrides) -> FareResult:
    kwargs = dict(
        site="google_flights",
        origin="JFK",
        destination="LAX",
        depart_date=date(2026, 9, 1),
        return_date=None,
        price=Decimal(price),
        currency="USD",
        deep_link="https://example.com/search",
        scraped_at=datetime(2026, 7, 28, 12, 0, 0),
        airline="JetBlue",
    )
    kwargs.update(overrides)
    return FareResult(**kwargs)


def test_insert_fare_returns_row_id(conn):
    fare_id = repository.insert_fare(conn, _make_fare("189.00"))
    assert fare_id > 0


def test_get_historical_min_returns_none_when_no_fares_recorded(conn):
    result = repository.get_historical_min(conn, "JFK", "LAX", date(2026, 9, 1), None)
    assert result is None


def test_get_historical_min_returns_lowest_price_seen(conn):
    repository.insert_fare(conn, _make_fare("250.00"))
    repository.insert_fare(conn, _make_fare("189.00"))
    repository.insert_fare(conn, _make_fare("310.00"))

    result = repository.get_historical_min(conn, "JFK", "LAX", date(2026, 9, 1), None)
    assert result == Decimal("189")


def test_get_historical_min_scopes_by_route_and_dates(conn):
    repository.insert_fare(conn, _make_fare("189.00"))
    repository.insert_fare(conn, _make_fare("99.00", destination="SFO"))

    result = repository.get_historical_min(conn, "JFK", "LAX", date(2026, 9, 1), None)
    assert result == Decimal("189")


def test_get_historical_min_handles_null_return_date_correctly(conn):
    repository.insert_fare(conn, _make_fare("189.00", return_date=None))
    repository.insert_fare(conn, _make_fare("500.00", return_date=date(2026, 9, 8)))

    one_way_min = repository.get_historical_min(conn, "JFK", "LAX", date(2026, 9, 1), None)
    round_trip_min = repository.get_historical_min(conn, "JFK", "LAX", date(2026, 9, 1), date(2026, 9, 8))

    assert one_way_min == Decimal("189")
    assert round_trip_min == Decimal("500")


def test_create_and_get_watch_round_trips(conn):
    watch = repository.create_watch(
        conn,
        WatchedRouteCreate(
            origin="JFK",
            destination="LAX",
            depart_date=date(2026, 9, 1),
            target_price=Decimal("200"),
            alert_email="me@example.com",
        ),
    )
    fetched = repository.get_watch(conn, watch.id)
    assert fetched is not None
    assert fetched.origin == "JFK"
    assert fetched.target_price == Decimal("200")
    assert fetched.is_active is True


def test_list_active_watches_excludes_deactivated(conn):
    watch = repository.create_watch(
        conn,
        WatchedRouteCreate(origin="JFK", destination="LAX", depart_date=date(2026, 9, 1)),
    )
    assert len(repository.list_active_watches(conn)) == 1

    repository.deactivate_watch(conn, watch.id)
    assert repository.list_active_watches(conn) == []
    assert len(repository.list_all_watches(conn)) == 1


def test_record_alert_and_scrape_health_do_not_raise(conn):
    watch = repository.create_watch(
        conn,
        WatchedRouteCreate(origin="JFK", destination="LAX", depart_date=date(2026, 9, 1)),
    )
    fare_id = repository.insert_fare(conn, _make_fare("189.00"), watched_route_id=watch.id)

    repository.record_alert(conn, watch.id, fare_id)
    repository.record_scrape_health(conn, "google_flights", "ok", None)

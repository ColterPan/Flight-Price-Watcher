import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from flight_fare_watcher.db import database, repository
from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.models.watch import WatchedRouteCreate

from ..conftest import future_date

DEPART = future_date()
RETURN = future_date(7)


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
        depart_date=DEPART,
        return_date=None,
        price=Decimal(price),
        currency="USD",
        deep_link="https://example.com/search",
        scraped_at=datetime(2026, 7, 28, 12, 0, 0),
        airline="JetBlue",
    )
    kwargs.update(overrides)
    return FareResult(**kwargs)


def _query(**overrides) -> SearchQuery:
    defaults = dict(origin="JFK", destination="LAX", depart_date=DEPART)
    defaults.update(overrides)
    return SearchQuery(**defaults)


def _watch(**overrides) -> WatchedRouteCreate:
    defaults = dict(origin="JFK", destination="LAX", depart_date=DEPART)
    defaults.update(overrides)
    return WatchedRouteCreate(**defaults)


# --- fares / history ---


def test_insert_fare_returns_row_id(conn):
    fare_id = repository.insert_fare(conn, _make_fare("189.00"))
    assert fare_id > 0


def test_get_historical_min_returns_none_when_no_fares_recorded(conn):
    result = repository.get_historical_min(conn, "JFK", "LAX", DEPART, None)
    assert result is None


def test_get_historical_min_returns_lowest_price_seen(conn):
    repository.insert_fare(conn, _make_fare("250.00"))
    repository.insert_fare(conn, _make_fare("189.00"))
    repository.insert_fare(conn, _make_fare("310.00"))

    assert repository.get_historical_min(conn, "JFK", "LAX", DEPART, None) == Decimal("189")


def test_get_historical_min_scopes_by_route_and_dates(conn):
    repository.insert_fare(conn, _make_fare("189.00"))
    repository.insert_fare(conn, _make_fare("99.00", destination="SFO"))

    assert repository.get_historical_min(conn, "JFK", "LAX", DEPART, None) == Decimal("189")


def test_get_historical_min_handles_null_return_date_correctly(conn):
    repository.insert_fare(conn, _make_fare("189.00", return_date=None))
    repository.insert_fare(conn, _make_fare("500.00", return_date=RETURN))

    one_way_min = repository.get_historical_min(conn, "JFK", "LAX", DEPART, None)
    round_trip_min = repository.get_historical_min(conn, "JFK", "LAX", DEPART, RETURN)

    assert one_way_min == Decimal("189")
    assert round_trip_min == Decimal("500")


def test_get_historical_min_does_not_mix_cabins_or_party_size(conn):
    # A 1-adult economy fare must never look like a lower price for a
    # 2-adult business watch - they are not comparable.
    repository.insert_fare(conn, _make_fare("150.00"), adults=1, cabin="economy")
    repository.insert_fare(conn, _make_fare("900.00"), adults=2, cabin="business")

    economy_min = repository.get_historical_min(conn, "JFK", "LAX", DEPART, None, adults=1, cabin="economy")
    business_min = repository.get_historical_min(conn, "JFK", "LAX", DEPART, None, adults=2, cabin="business")

    assert economy_min == Decimal("150")
    assert business_min == Decimal("900")


def test_record_search_fares_persists_every_fare_once(conn):
    fares = [_make_fare("189.00"), _make_fare("250.00", carrier_code="AA")]
    inserted = repository.record_search_fares(conn, _query(), fares)

    assert all(row_id > 0 for row_id in inserted)
    count = conn.execute("SELECT COUNT(*) AS c FROM fares").fetchone()["c"]
    assert count == 2


def test_record_search_fares_skips_recent_exact_duplicate(conn):
    # Re-running an identical search moments later must not double the
    # history - otherwise every repeat search inflates the price chart.
    # scraped_at must be "now" (as a real scrape produces), not the fixture's
    # default fixed timestamp, since the dedup window is relative to now().
    fare = _make_fare("189.00", depart_time="6:00 AM", scraped_at=datetime.now())
    first = repository.record_search_fares(conn, _query(), [fare])
    second = repository.record_search_fares(conn, _query(), [fare])

    assert first[0] > 0
    assert second == [-1]
    count = conn.execute("SELECT COUNT(*) AS c FROM fares").fetchone()["c"]
    assert count == 1


def test_get_price_history_returns_one_point_per_scrape_oldest_first(conn):
    early = _make_fare("300.00", scraped_at=datetime(2026, 1, 1, 9, 0))
    later_cheap = _make_fare("150.00", scraped_at=datetime(2026, 1, 2, 9, 0))
    later_decoy = _make_fare("999.00", scraped_at=datetime(2026, 1, 2, 9, 0))
    for fare in (early, later_cheap, later_decoy):
        repository.insert_fare(conn, fare)

    points = repository.get_price_history(conn, "JFK", "LAX", DEPART, None)
    assert [p["price"] for p in points] == [300.0, 150.0]


# --- watches ---


def test_create_and_get_watch_round_trips(conn):
    watch = repository.create_watch(
        conn, _watch(target_price=Decimal("200"), alert_email="me@example.com")
    )
    fetched = repository.get_watch(conn, watch.id)
    assert fetched is not None
    assert fetched.origin == "JFK"
    assert fetched.target_price == Decimal("200")
    assert fetched.is_active is True
    assert fetched.adults == 1
    assert fetched.cabin == "economy"


def test_create_watch_rejects_duplicate_active_route(conn):
    repository.create_watch(conn, _watch())
    with pytest.raises(sqlite3.IntegrityError):
        repository.create_watch(conn, _watch())


def test_create_watch_allows_same_route_with_different_party_size(conn):
    repository.create_watch(conn, _watch(adults=1))
    second = repository.create_watch(conn, _watch(adults=2))
    assert second.adults == 2
    assert len(repository.list_active_watches(conn)) == 2


def test_removing_and_readding_a_watch_reactivates_it_instead_of_erroring(conn):
    # This is the core bug this version fixes: removal is a soft delete (kept
    # for the fares table's foreign key), and the UNIQUE index on
    # (origin, destination, depart_date, return_date, adults, cabin) means a
    # plain INSERT for a previously removed route fails forever unless
    # create_watch special-cases reviving it.
    original = repository.create_watch(conn, _watch(target_price=Decimal("300")))
    repository.deactivate_watch(conn, original.id)
    assert repository.list_active_watches(conn) == []

    revived = repository.create_watch(conn, _watch(target_price=Decimal("250")))

    assert revived.id == original.id  # same row, not a new one
    assert revived.is_active is True
    assert revived.target_price == Decimal("250")  # new target applied
    assert len(repository.list_active_watches(conn)) == 1


def test_list_all_watches_excludes_removed_routes(conn):
    watch = repository.create_watch(conn, _watch())
    assert len(repository.list_all_watches(conn)) == 1

    repository.deactivate_watch(conn, watch.id)
    # A removed watch is kept only so `fares` keeps a valid foreign key - it
    # must not still show up anywhere the user looks.
    assert repository.list_all_watches(conn) == []


def test_update_watch_check_result_is_reflected_on_the_watch(conn):
    watch = repository.create_watch(conn, _watch())
    repository.update_watch_check_result(conn, watch.id, "ok", Decimal("275.50"))

    updated = repository.get_watch(conn, watch.id)
    assert updated.last_status == "ok"
    assert updated.last_price == Decimal("275.5")
    assert updated.last_checked_at is not None


def test_record_alert_and_count(conn):
    watch = repository.create_watch(conn, _watch())
    fare_id = repository.insert_fare(conn, _make_fare("189.00"), watched_route_id=watch.id)

    assert repository.count_alerts_for_watch(conn, watch.id) == 0
    repository.record_alert(conn, watch.id, fare_id)
    assert repository.count_alerts_for_watch(conn, watch.id) == 1


def test_scrape_health_reports_latest_status_per_site(conn):
    repository.record_scrape_health(conn, "google_flights", "ok", None)
    repository.record_scrape_health(conn, "google_flights", "blocked_or_structure_changed", "captcha")
    repository.record_scrape_health(conn, "amadeus", "not_configured", "no API key")

    latest = {row["site"]: row for row in repository.latest_scrape_health(conn)}
    assert latest["google_flights"]["status"] == "blocked_or_structure_changed"
    assert latest["amadeus"]["status"] == "not_configured"

from datetime import datetime
from decimal import Decimal

import pytest

from flight_fare_watcher.config import Settings
from flight_fare_watcher.db import repository
from flight_fare_watcher.db.database import connect
from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.watch import WatchedRouteCreate
from flight_fare_watcher.scheduler import jobs as scheduler_jobs
from flight_fare_watcher.search.orchestrator import SearchResponse

from ..conftest import future_date

DEPART = future_date()


def _settings(**overrides) -> Settings:
    base = dict(
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        alert_from_email="watcher@example.com",
        alert_to_email="me@example.com",
        database_path=":memory:",
        enabled_sites="google_flights",
    )
    base.update(overrides)
    return Settings(**base)


def _fare(price: str, site: str = "google_flights", **overrides) -> FareResult:
    kwargs = dict(
        site=site,
        origin="JFK",
        destination="LAX",
        depart_date=DEPART,
        return_date=None,
        price=Decimal(price),
        currency="USD",
        deep_link="https://example.com/search",
        scraped_at=datetime.now(),
        airline="Test Air",
    )
    kwargs.update(overrides)
    return FareResult(**kwargs)


def _response(fares, statuses, diagnostics=None) -> SearchResponse:
    return SearchResponse(
        origin="JFK",
        destination="LAX",
        depart_date=DEPART,
        return_date=None,
        fares=fares,
        site_statuses=statuses,
        site_diagnostics=diagnostics or {},
    )


def _watch(**overrides) -> WatchedRouteCreate:
    defaults = dict(origin="JFK", destination="LAX", depart_date=DEPART)
    defaults.update(overrides)
    return WatchedRouteCreate(**defaults)


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


@pytest.mark.asyncio
async def test_check_watch_sends_alert_and_records_it_on_new_low_below_target(conn, monkeypatch):
    watch = repository.create_watch(conn, _watch(target_price=Decimal("200")))
    repository.insert_fare(conn, _fare("250"), watched_route_id=watch.id)  # existing historical min

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        return _response([_fare("189")], {"google_flights": "ok"})

    sent_alerts = []
    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)
    monkeypatch.setattr(
        scheduler_jobs.mailer,
        "send_price_alert",
        lambda settings, to, subject, body: sent_alerts.append((to, subject)),
    )

    await scheduler_jobs.check_watch(conn, watch, _settings())

    assert len(sent_alerts) == 1
    assert sent_alerts[0][0] == "me@example.com"
    alert_rows = conn.execute("SELECT COUNT(*) AS c FROM alert_log").fetchone()
    assert alert_rows["c"] == 1


@pytest.mark.asyncio
async def test_check_watch_survives_a_failed_alert_email_and_keeps_the_real_result(conn, monkeypatch):
    # Regression: an SMTP failure while sending the alert must not look like
    # "the search failed" - fares were genuinely found and already persisted,
    # so the watch's status/price must still reflect that, and the caller
    # must get the cheapest price back rather than an exception.
    watch = repository.create_watch(conn, _watch(target_price=Decimal("200")))

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        return _response([_fare("189")], {"google_flights": "ok"})

    def failing_send(*args, **kwargs):
        raise OSError("Connection unexpectedly closed")

    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)
    monkeypatch.setattr(scheduler_jobs.mailer, "send_price_alert", failing_send)

    cheapest = await scheduler_jobs.check_watch(conn, watch, _settings())

    assert cheapest == Decimal("189")
    updated = repository.get_watch(conn, watch.id)
    assert updated.last_status == "ok"
    assert updated.last_price == Decimal("189")
    # No alert_log row either - the email never actually went out.
    assert repository.count_alerts_for_watch(conn, watch.id) == 0


@pytest.mark.asyncio
async def test_check_watch_does_not_alert_when_price_is_above_target(conn, monkeypatch):
    watch = repository.create_watch(conn, _watch(target_price=Decimal("100")))

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        return _response([_fare("189")], {"google_flights": "ok"})

    sent_alerts = []
    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)
    monkeypatch.setattr(scheduler_jobs.mailer, "send_price_alert", lambda *a, **k: sent_alerts.append(a))

    await scheduler_jobs.check_watch(conn, watch, _settings())

    assert sent_alerts == []
    fares_count = conn.execute("SELECT COUNT(*) AS c FROM fares").fetchone()["c"]
    assert fares_count == 1  # still persisted for price history, just no alert


@pytest.mark.asyncio
async def test_check_watch_handles_no_fares_found_without_error(conn, monkeypatch):
    watch = repository.create_watch(conn, _watch())

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        return _response([], {"google_flights": "no_results"})

    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)
    monkeypatch.setattr(
        scheduler_jobs.mailer, "send_price_alert", lambda *a, **k: pytest.fail("should not send alert")
    )

    cheapest = await scheduler_jobs.check_watch(conn, watch, _settings())
    assert cheapest is None

    updated = repository.get_watch(conn, watch.id)
    assert updated.last_status == "no_results"


@pytest.mark.asyncio
async def test_check_watch_records_scrape_health_per_site(conn, monkeypatch):
    watch = repository.create_watch(conn, _watch())

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        return _response([], {"google_flights": "blocked_or_structure_changed"})

    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)

    await scheduler_jobs.check_watch(conn, watch, _settings())

    health_rows = conn.execute("SELECT status FROM scrape_health").fetchall()
    assert [r["status"] for r in health_rows] == ["blocked_or_structure_changed"]


@pytest.mark.asyncio
async def test_check_watch_scopes_historical_min_by_adults_and_cabin(conn, monkeypatch):
    # A cheap 1-adult economy fare recorded earlier must not suppress an
    # alert on a 2-adult business watch - they are not the same product.
    watch = repository.create_watch(conn, _watch(adults=2, cabin="business"))
    repository.insert_fare(conn, _fare("150"), adults=1, cabin="economy")

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        return _response([_fare("900")], {"google_flights": "ok"})

    sent_alerts = []
    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)
    monkeypatch.setattr(
        scheduler_jobs.mailer, "send_price_alert", lambda *a, **k: sent_alerts.append(a)
    )

    await scheduler_jobs.check_watch(conn, watch, _settings())

    # No target price set -> any new low alerts. Since nothing has been
    # recorded yet under (adults=2, cabin=business), $900 is a new low.
    assert len(sent_alerts) == 1


@pytest.mark.asyncio
async def test_run_watch_check_job_continues_after_one_watch_raises(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = connect(db_path)
    watch_a = repository.create_watch(conn, _watch())
    watch_b = repository.create_watch(conn, _watch(origin="SFO", destination="ORD"))
    conn.close()

    checked = []

    async def fake_check_watch(conn, watch, settings):
        checked.append(watch.id)
        if watch.id == watch_a.id:
            raise RuntimeError("simulated scrape failure")

    monkeypatch.setattr(scheduler_jobs, "check_watch", fake_check_watch)

    await scheduler_jobs.run_watch_check_job(db_path, _settings(database_path=db_path))

    assert set(checked) == {watch_a.id, watch_b.id}

    # The failed watch's status must still be recorded as a failure rather
    # than left looking untouched, so the UI does not imply it succeeded.
    conn = connect(db_path)
    failed_watch = repository.get_watch(conn, watch_a.id)
    conn.close()
    assert failed_watch.last_status == "error"

from datetime import date, datetime
from decimal import Decimal

import pytest

from flight_fare_watcher.config import Settings
from flight_fare_watcher.db import repository
from flight_fare_watcher.db.database import connect
from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.watch import WatchedRouteCreate
from flight_fare_watcher.scheduler import jobs as scheduler_jobs
from flight_fare_watcher.search.orchestrator import SearchResponse


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


def _fare(price: str, site: str = "google_flights") -> FareResult:
    return FareResult(
        site=site,
        origin="JFK",
        destination="LAX",
        depart_date=date(2026, 9, 1),
        return_date=None,
        price=Decimal(price),
        currency="USD",
        deep_link="https://example.com/search",
        scraped_at=datetime(2026, 7, 28, 12, 0, 0),
        airline="Test Air",
    )


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


@pytest.mark.asyncio
async def test_check_watch_sends_alert_and_records_it_on_new_low_below_target(conn, monkeypatch):
    watch = repository.create_watch(
        conn,
        WatchedRouteCreate(origin="JFK", destination="LAX", depart_date=date(2026, 9, 1), target_price=Decimal("200")),
    )
    repository.insert_fare(conn, _fare("250"), watched_route_id=watch.id)  # existing historical min

    async def fake_run_search(*args, **kwargs):
        return SearchResponse(
            origin="JFK", destination="LAX", depart_date=date(2026, 9, 1), return_date=None,
            fares=[_fare("189")], site_statuses={"google_flights": "ok"},
        )

    sent_alerts = []
    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)
    monkeypatch.setattr(scheduler_jobs.mailer, "send_price_alert", lambda settings, to, subject, body: sent_alerts.append((to, subject)))

    await scheduler_jobs.check_watch(conn, watch, _settings())

    assert len(sent_alerts) == 1
    assert sent_alerts[0][0] == "me@example.com"
    alert_rows = conn.execute("SELECT COUNT(*) AS c FROM alert_log").fetchone()
    assert alert_rows["c"] == 1


@pytest.mark.asyncio
async def test_check_watch_does_not_alert_when_price_is_above_target(conn, monkeypatch):
    watch = repository.create_watch(
        conn,
        WatchedRouteCreate(origin="JFK", destination="LAX", depart_date=date(2026, 9, 1), target_price=Decimal("100")),
    )

    async def fake_run_search(*args, **kwargs):
        return SearchResponse(
            origin="JFK", destination="LAX", depart_date=date(2026, 9, 1), return_date=None,
            fares=[_fare("189")], site_statuses={"google_flights": "ok"},
        )

    sent_alerts = []
    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)
    monkeypatch.setattr(scheduler_jobs.mailer, "send_price_alert", lambda *a, **k: sent_alerts.append(a))

    await scheduler_jobs.check_watch(conn, watch, _settings())

    assert sent_alerts == []
    fares_count = conn.execute("SELECT COUNT(*) AS c FROM fares").fetchone()["c"]
    assert fares_count == 1  # still persisted for price history, just no alert


@pytest.mark.asyncio
async def test_check_watch_handles_no_fares_found_without_error(conn, monkeypatch):
    watch = repository.create_watch(
        conn, WatchedRouteCreate(origin="JFK", destination="LAX", depart_date=date(2026, 9, 1))
    )

    async def fake_run_search(*args, **kwargs):
        return SearchResponse(
            origin="JFK", destination="LAX", depart_date=date(2026, 9, 1), return_date=None,
            fares=[], site_statuses={"google_flights": "no_results"},
        )

    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)
    monkeypatch.setattr(scheduler_jobs.mailer, "send_price_alert", lambda *a, **k: pytest.fail("should not send alert"))

    await scheduler_jobs.check_watch(conn, watch, _settings())


@pytest.mark.asyncio
async def test_check_watch_records_scrape_health_per_site(conn, monkeypatch):
    watch = repository.create_watch(
        conn, WatchedRouteCreate(origin="JFK", destination="LAX", depart_date=date(2026, 9, 1))
    )

    async def fake_run_search(*args, **kwargs):
        return SearchResponse(
            origin="JFK", destination="LAX", depart_date=date(2026, 9, 1), return_date=None,
            fares=[], site_statuses={"google_flights": "blocked_or_structure_changed"},
        )

    monkeypatch.setattr(scheduler_jobs, "run_search", fake_run_search)

    await scheduler_jobs.check_watch(conn, watch, _settings())

    health_rows = conn.execute("SELECT status FROM scrape_health").fetchall()
    assert [r["status"] for r in health_rows] == ["blocked_or_structure_changed"]


@pytest.mark.asyncio
async def test_run_watch_check_job_continues_after_one_watch_raises(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = connect(db_path)
    watch_a = repository.create_watch(conn, WatchedRouteCreate(origin="JFK", destination="LAX", depart_date=date(2026, 9, 1)))
    watch_b = repository.create_watch(conn, WatchedRouteCreate(origin="SFO", destination="ORD", depart_date=date(2026, 9, 1)))
    conn.close()

    checked = []

    async def fake_check_watch(conn, watch, settings):
        checked.append(watch.id)
        if watch.id == watch_a.id:
            raise RuntimeError("simulated scrape failure")

    monkeypatch.setattr(scheduler_jobs, "check_watch", fake_check_watch)

    await scheduler_jobs.run_watch_check_job(db_path, _settings(database_path=db_path))

    assert set(checked) == {watch_a.id, watch_b.id}

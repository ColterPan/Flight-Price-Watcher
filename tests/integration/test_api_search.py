from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from flight_fare_watcher.db.database import connect
from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome
from flight_fare_watcher.search.orchestrator import build_response
from flight_fare_watcher.web import routes_search
from flight_fare_watcher.web.app import create_app


def _fare(site: str, price: str) -> FareResult:
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
def client(monkeypatch):
    app = create_app()

    test_conn = connect(":memory:")

    def override_get_db():
        yield test_conn

    app.dependency_overrides[routes_search.get_db] = override_get_db

    yield TestClient(app), test_conn
    test_conn.close()


def test_search_returns_cheapest_fares_sorted_ascending(client, monkeypatch):
    test_client, _conn = client

    async def fake_run_search(adapters, origin, destination, depart_date, return_date, headless=True):
        outcomes = [
            ScrapeOutcome(site="google_flights", status="ok", fares=[_fare("google_flights", "351"), _fare("google_flights", "189")]),
        ]
        return build_response(origin, destination, depart_date, return_date, outcomes)

    monkeypatch.setattr(routes_search, "run_search", fake_run_search)
    monkeypatch.setattr(routes_search, "build_enabled_adapters", lambda *a, **k: ["fake_adapter"])

    response = test_client.post(
        "/api/search",
        json={"origin": "JFK", "destination": "LAX", "depart_date": "2026-09-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [f["price"] for f in body["fares"]] == ["189", "351"]
    assert body["site_statuses"] == {"google_flights": "ok"}


def test_search_surfaces_partial_site_failure_without_failing_whole_request(client, monkeypatch):
    test_client, _conn = client

    async def fake_run_search(adapters, origin, destination, depart_date, return_date, headless=True):
        outcomes = [
            ScrapeOutcome(site="google_flights", status="ok", fares=[_fare("google_flights", "220")]),
            ScrapeOutcome(site="kiwi", status="blocked_or_structure_changed", diagnostic="unexpected page title"),
        ]
        return build_response(origin, destination, depart_date, return_date, outcomes)

    monkeypatch.setattr(routes_search, "run_search", fake_run_search)
    monkeypatch.setattr(routes_search, "build_enabled_adapters", lambda *a, **k: ["fake_adapter"])

    response = test_client.post(
        "/api/search",
        json={"origin": "JFK", "destination": "LAX", "depart_date": "2026-09-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["fares"]) == 1
    assert body["site_statuses"]["kiwi"] == "blocked_or_structure_changed"


def test_search_persists_fares_for_price_history(client, monkeypatch):
    test_client, conn = client

    async def fake_run_search(adapters, origin, destination, depart_date, return_date, headless=True):
        outcomes = [ScrapeOutcome(site="google_flights", status="ok", fares=[_fare("google_flights", "199")])]
        return build_response(origin, destination, depart_date, return_date, outcomes)

    monkeypatch.setattr(routes_search, "run_search", fake_run_search)
    monkeypatch.setattr(routes_search, "build_enabled_adapters", lambda *a, **k: ["fake_adapter"])

    test_client.post("/api/search", json={"origin": "JFK", "destination": "LAX", "depart_date": "2026-09-01"})

    row = conn.execute("SELECT COUNT(*) AS c FROM fares").fetchone()
    assert row["c"] == 1


def test_search_rejects_malformed_request():
    app = create_app()
    test_client = TestClient(app)
    response = test_client.post("/api/search", json={"origin": "JFK"})
    assert response.status_code == 422

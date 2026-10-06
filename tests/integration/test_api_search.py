from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from flight_fare_watcher.db.database import connect
from flight_fare_watcher.models.fare import FareResult, ScrapeOutcome
from flight_fare_watcher.search.orchestrator import build_response
from flight_fare_watcher.web import routes_search
from flight_fare_watcher.web.app import create_app

from ..conftest import future_date

DEPART = future_date().isoformat()


def _fare(site: str, price: str) -> FareResult:
    return FareResult(
        site=site,
        origin="JFK",
        destination="LAX",
        depart_date=future_date(),
        return_date=None,
        price=Decimal(price),
        currency="USD",
        deep_link="https://example.com/search",
        scraped_at=datetime.now(),
        airline="Test Air",
    )


@pytest.fixture
def client():
    app = create_app()
    test_conn = connect(":memory:")

    def override_get_db():
        yield test_conn

    app.dependency_overrides[routes_search.get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client, test_conn

    test_conn.close()


def test_search_returns_cheapest_fares_sorted_ascending(client, monkeypatch):
    test_client, _conn = client

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        outcomes = [
            ScrapeOutcome(
                site="google_flights",
                status="ok",
                fares=[_fare("google_flights", "351"), _fare("google_flights", "189")],
            ),
        ]
        return build_response(query, outcomes)

    monkeypatch.setattr(routes_search, "run_search", fake_run_search)
    monkeypatch.setattr(routes_search, "build_adapters_from_settings", lambda settings: ["fake_adapter"])

    response = test_client.post(
        "/api/search", json={"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    )

    assert response.status_code == 200
    body = response.json()
    assert [f["price"] for f in body["fares"]] == ["189", "351"]
    assert body["site_statuses"] == {"google_flights": "ok"}


def test_search_surfaces_partial_site_failure_without_failing_whole_request(client, monkeypatch):
    test_client, _conn = client

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        outcomes = [
            ScrapeOutcome(site="google_flights", status="ok", fares=[_fare("google_flights", "220")]),
            ScrapeOutcome(
                site="amadeus", status="not_configured", diagnostic="set AMADEUS_API_KEY"
            ),
        ]
        return build_response(query, outcomes)

    monkeypatch.setattr(routes_search, "run_search", fake_run_search)
    monkeypatch.setattr(routes_search, "build_adapters_from_settings", lambda settings: ["fake_adapter"])

    response = test_client.post(
        "/api/search", json={"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["fares"]) == 1
    assert body["site_statuses"]["amadeus"] == "not_configured"
    assert body["site_diagnostics"]["amadeus"] == "set AMADEUS_API_KEY"


def test_search_persists_fares_for_price_history(client, monkeypatch):
    test_client, conn = client

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        outcomes = [ScrapeOutcome(site="google_flights", status="ok", fares=[_fare("google_flights", "199")])]
        return build_response(query, outcomes)

    monkeypatch.setattr(routes_search, "run_search", fake_run_search)
    monkeypatch.setattr(routes_search, "build_adapters_from_settings", lambda settings: ["fake_adapter"])

    test_client.post("/api/search", json={"origin": "JFK", "destination": "LAX", "depart_date": DEPART})

    row = conn.execute("SELECT COUNT(*) AS c FROM fares").fetchone()
    assert row["c"] == 1


def test_search_second_identical_request_is_served_from_cache(client, monkeypatch):
    test_client, _conn = client
    call_count = 0

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        nonlocal call_count
        call_count += 1
        outcomes = [ScrapeOutcome(site="google_flights", status="ok", fares=[_fare("google_flights", "199")])]
        return build_response(query, outcomes)

    monkeypatch.setattr(routes_search, "run_search", fake_run_search)
    monkeypatch.setattr(routes_search, "build_adapters_from_settings", lambda settings: ["fake_adapter"])

    payload = {"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    first = test_client.post("/api/search", json=payload)
    second = test_client.post("/api/search", json=payload)

    assert call_count == 1  # the provider was only actually invoked once
    assert first.json()["from_cache"] is False
    assert second.json()["from_cache"] is True


def test_search_refresh_bypasses_the_cache(client, monkeypatch):
    test_client, _conn = client
    call_count = 0

    async def fake_run_search(adapters, query, headless=True, booking_link_resolve_count=0):
        nonlocal call_count
        call_count += 1
        outcomes = [ScrapeOutcome(site="google_flights", status="ok", fares=[_fare("google_flights", "199")])]
        return build_response(query, outcomes)

    monkeypatch.setattr(routes_search, "run_search", fake_run_search)
    monkeypatch.setattr(routes_search, "build_adapters_from_settings", lambda settings: ["fake_adapter"])

    payload = {"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    test_client.post("/api/search", json=payload)
    test_client.post("/api/search", json={**payload, "refresh": True})

    assert call_count == 2


def test_search_rejects_malformed_request():
    app = create_app()
    test_client = TestClient(app)
    response = test_client.post("/api/search", json={"origin": "JFK"})
    assert response.status_code == 422


def test_search_rejects_invalid_airport_code():
    app = create_app()
    test_client = TestClient(app)
    response = test_client.post(
        "/api/search", json={"origin": "NEWYORK", "destination": "LAX", "depart_date": DEPART}
    )
    assert response.status_code == 422


def test_search_rejects_same_origin_and_destination():
    app = create_app()
    test_client = TestClient(app)
    response = test_client.post(
        "/api/search", json={"origin": "JFK", "destination": "JFK", "depart_date": DEPART}
    )
    assert response.status_code == 422


def test_search_rejects_return_date_before_depart_date():
    app = create_app()
    test_client = TestClient(app)
    depart = future_date(30)
    earlier_return = future_date(10)
    response = test_client.post(
        "/api/search",
        json={
            "origin": "JFK",
            "destination": "LAX",
            "depart_date": depart.isoformat(),
            "return_date": earlier_return.isoformat(),
        },
    )
    assert response.status_code == 422

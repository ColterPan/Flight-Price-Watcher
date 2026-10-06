from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from flight_fare_watcher.currency import ExchangeRateError, ExchangeRateSnapshot
from flight_fare_watcher.web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_exchange_rates_returns_live_rates(client, monkeypatch):
    async def fake_fetch(base):
        return ExchangeRateSnapshot(
            base=base,
            rates={"EUR": Decimal("0.9"), "GBP": Decimal("0.75")},
            as_of="2026-10-05",
            fetched_at=0.0,
        )

    import flight_fare_watcher.currency as currency_module

    monkeypatch.setattr(currency_module, "fetch_live_rates", fake_fetch)

    response = client.get("/api/exchange-rates?base=USD")
    assert response.status_code == 200
    body = response.json()
    assert body["base"] == "USD"
    assert body["rates"]["EUR"] == "0.9"
    assert body["stale"] is False
    assert "USD" in body["supported_currencies"]


def test_exchange_rates_rejects_unsupported_currency(client):
    response = client.get("/api/exchange-rates?base=ZZZ")
    assert response.status_code == 422


def test_exchange_rates_returns_503_when_nothing_available(client, monkeypatch):
    import flight_fare_watcher.currency as currency_module

    async def failing_fetch(base):
        raise ExchangeRateError("simulated outage")

    monkeypatch.setattr(currency_module, "fetch_live_rates", failing_fetch)

    response = client.get("/api/exchange-rates?base=EUR")
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()

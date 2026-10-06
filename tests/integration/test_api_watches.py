import pytest
from fastapi.testclient import TestClient

from flight_fare_watcher.db.database import connect
from flight_fare_watcher.web import routes_search, routes_watches
from flight_fare_watcher.web.app import create_app

from ..conftest import future_date

DEPART = future_date().isoformat()


@pytest.fixture
def client():
    app = create_app()
    test_conn = connect(":memory:")

    def override_get_db():
        yield test_conn

    app.dependency_overrides[routes_search.get_db] = override_get_db
    app.dependency_overrides[routes_watches.get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client, test_conn

    test_conn.close()


def test_create_watch_returns_201_with_watch_payload(client):
    test_client, _conn = client
    response = test_client.post(
        "/api/watches",
        json={"origin": "JFK", "destination": "LAX", "depart_date": DEPART, "target_price": "200"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["origin"] == "JFK"
    assert body["is_active"] is True
    assert body["id"] > 0
    assert body["adults"] == 1
    assert body["cabin"] == "economy"


def test_create_duplicate_watch_returns_409(client):
    test_client, _conn = client
    payload = {"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    first = test_client.post("/api/watches", json=payload)
    assert first.status_code == 201

    second = test_client.post("/api/watches", json=payload)
    assert second.status_code == 409


def test_create_watch_accepts_city_names_resolved_to_airport_codes_already_uppercased(client):
    test_client, _conn = client
    response = test_client.post(
        "/api/watches", json={"origin": "jfk", "destination": "lax", "depart_date": DEPART}
    )
    assert response.status_code == 201
    assert response.json()["origin"] == "JFK"
    assert response.json()["destination"] == "LAX"


def test_create_watch_rejects_past_depart_date(client):
    test_client, _conn = client
    response = test_client.post(
        "/api/watches", json={"origin": "JFK", "destination": "LAX", "depart_date": "2020-01-01"}
    )
    assert response.status_code == 422


def test_list_watches_returns_created_watch(client):
    test_client, _conn = client
    test_client.post("/api/watches", json={"origin": "JFK", "destination": "LAX", "depart_date": DEPART})

    response = test_client.get("/api/watches")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["origin"] == "JFK"


def test_delete_watch_removes_it_from_the_list(client):
    test_client, _conn = client
    created = test_client.post(
        "/api/watches", json={"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    ).json()

    delete_response = test_client.delete(f"/api/watches/{created['id']}")
    assert delete_response.status_code == 204

    # A removed watch is soft-deleted internally (so fare history keeps a
    # valid foreign key) but must not still appear anywhere the user looks.
    list_response = test_client.get("/api/watches").json()
    assert list_response == []


def test_readding_a_removed_watch_reactivates_it_instead_of_409(client):
    test_client, _conn = client
    payload = {"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    created = test_client.post("/api/watches", json=payload).json()
    test_client.delete(f"/api/watches/{created['id']}")

    second = test_client.post("/api/watches", json=payload)
    assert second.status_code == 201
    assert second.json()["id"] == created["id"]
    assert second.json()["is_active"] is True


def test_delete_nonexistent_watch_returns_404(client):
    test_client, _conn = client
    response = test_client.delete("/api/watches/999")
    assert response.status_code == 404


def test_check_watch_now_returns_404_for_missing_watch(client):
    test_client, _conn = client
    response = test_client.post("/api/watches/999/check")
    assert response.status_code == 404


def test_check_watch_now_runs_a_real_check_and_updates_status(client, monkeypatch):
    test_client, _conn = client
    created = test_client.post(
        "/api/watches", json={"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    ).json()

    from decimal import Decimal

    from flight_fare_watcher.web import routes_watches as routes_watches_module

    async def fake_check_watch(conn, watch, settings):
        from flight_fare_watcher.db import repository

        repository.update_watch_check_result(conn, watch.id, "ok", Decimal("222"))
        return Decimal("222")

    monkeypatch.setattr(routes_watches_module, "check_watch", fake_check_watch)

    response = test_client.post(f"/api/watches/{created['id']}/check")
    assert response.status_code == 200
    body = response.json()
    assert body["cheapest_price"] == "222"
    assert body["status"] == "ok"


def test_watch_history_returns_empty_series_before_any_check(client):
    test_client, _conn = client
    created = test_client.post(
        "/api/watches", json={"origin": "JFK", "destination": "LAX", "depart_date": DEPART}
    ).json()

    response = test_client.get(f"/api/watches/{created['id']}/history")
    assert response.status_code == 200
    body = response.json()
    assert body["points"] == []
    assert body["alerts_sent"] == 0


def test_watch_history_returns_404_for_missing_watch(client):
    test_client, _conn = client
    response = test_client.get("/api/watches/999/history")
    assert response.status_code == 404

import pytest
from fastapi.testclient import TestClient

from flight_fare_watcher.db.database import connect
from flight_fare_watcher.web import routes_search, routes_watches
from flight_fare_watcher.web.app import create_app


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
        json={"origin": "JFK", "destination": "LAX", "depart_date": "2026-09-01", "target_price": "200"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["origin"] == "JFK"
    assert body["is_active"] is True
    assert body["id"] > 0


def test_create_duplicate_watch_returns_409(client):
    test_client, _conn = client
    payload = {"origin": "JFK", "destination": "LAX", "depart_date": "2026-09-01"}
    first = test_client.post("/api/watches", json=payload)
    assert first.status_code == 201

    second = test_client.post("/api/watches", json=payload)
    assert second.status_code == 409


def test_list_watches_returns_created_watch(client):
    test_client, _conn = client
    test_client.post("/api/watches", json={"origin": "JFK", "destination": "LAX", "depart_date": "2026-09-01"})

    response = test_client.get("/api/watches")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["origin"] == "JFK"


def test_delete_watch_deactivates_it(client):
    test_client, _conn = client
    created = test_client.post(
        "/api/watches", json={"origin": "JFK", "destination": "LAX", "depart_date": "2026-09-01"}
    ).json()

    delete_response = test_client.delete(f"/api/watches/{created['id']}")
    assert delete_response.status_code == 204

    list_response = test_client.get("/api/watches").json()
    assert list_response[0]["is_active"] is False


def test_delete_nonexistent_watch_returns_404(client):
    test_client, _conn = client
    response = test_client.delete("/api/watches/999")
    assert response.status_code == 404

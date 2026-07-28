"""Thin data-access functions for the fare/watch/alert tables.

Plain sqlite3 + explicit functions rather than an ORM: the schema is four
small tables, and this is simpler to unit test against an in-memory database.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal

from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.watch import WatchedRoute, WatchedRouteCreate


def _date_str(value: date | None) -> str | None:
    return value.isoformat() if value else None


def insert_fare(conn: sqlite3.Connection, fare: FareResult, watched_route_id: int | None = None) -> int:
    cursor = conn.execute(
        """
        INSERT INTO fares (
            watched_route_id, origin, destination, depart_date, return_date,
            site, price, currency, deep_link, scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            watched_route_id,
            fare.origin,
            fare.destination,
            _date_str(fare.depart_date),
            _date_str(fare.return_date),
            fare.site,
            float(fare.price),
            fare.currency,
            fare.deep_link,
            fare.scraped_at.isoformat(),
        ),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def get_historical_min(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
) -> Decimal | None:
    row = conn.execute(
        """
        SELECT MIN(price) AS min_price FROM fares
        WHERE origin = ? AND destination = ? AND depart_date = ?
          AND (return_date IS ? OR return_date = ?)
        """,
        (origin, destination, _date_str(depart_date), _date_str(return_date), _date_str(return_date)),
    ).fetchone()
    if row is None or row["min_price"] is None:
        return None
    return Decimal(str(row["min_price"]))


def create_watch(conn: sqlite3.Connection, watch: WatchedRouteCreate) -> WatchedRoute:
    created_at = datetime.now()
    cursor = conn.execute(
        """
        INSERT INTO watched_routes (
            origin, destination, depart_date, return_date, target_price,
            currency, alert_email, is_active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            watch.origin,
            watch.destination,
            _date_str(watch.depart_date),
            _date_str(watch.return_date),
            float(watch.target_price) if watch.target_price is not None else None,
            watch.currency,
            watch.alert_email,
            created_at.isoformat(),
        ),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return get_watch(conn, cursor.lastrowid)  # type: ignore[return-value]


def _row_to_watch(row: sqlite3.Row) -> WatchedRoute:
    return WatchedRoute(
        id=row["id"],
        origin=row["origin"],
        destination=row["destination"],
        depart_date=date.fromisoformat(row["depart_date"]),
        return_date=date.fromisoformat(row["return_date"]) if row["return_date"] else None,
        target_price=Decimal(str(row["target_price"])) if row["target_price"] is not None else None,
        currency=row["currency"],
        alert_email=row["alert_email"],
        is_active=bool(row["is_active"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def get_watch(conn: sqlite3.Connection, watch_id: int) -> WatchedRoute | None:
    row = conn.execute("SELECT * FROM watched_routes WHERE id = ?", (watch_id,)).fetchone()
    return _row_to_watch(row) if row else None


def list_active_watches(conn: sqlite3.Connection) -> list[WatchedRoute]:
    rows = conn.execute("SELECT * FROM watched_routes WHERE is_active = 1").fetchall()
    return [_row_to_watch(row) for row in rows]


def list_all_watches(conn: sqlite3.Connection) -> list[WatchedRoute]:
    rows = conn.execute("SELECT * FROM watched_routes ORDER BY created_at DESC").fetchall()
    return [_row_to_watch(row) for row in rows]


def deactivate_watch(conn: sqlite3.Connection, watch_id: int) -> None:
    conn.execute("UPDATE watched_routes SET is_active = 0 WHERE id = ?", (watch_id,))
    conn.commit()


def record_alert(conn: sqlite3.Connection, watched_route_id: int, fare_id: int) -> None:
    conn.execute(
        "INSERT INTO alert_log (watched_route_id, fare_id, sent_at) VALUES (?, ?, ?)",
        (watched_route_id, fare_id, datetime.now().isoformat()),
    )
    conn.commit()


def record_scrape_health(conn: sqlite3.Connection, site: str, status: str, detail: str | None) -> None:
    conn.execute(
        "INSERT INTO scrape_health (site, checked_at, status, detail) VALUES (?, ?, ?, ?)",
        (site, datetime.now().isoformat(), status, detail),
    )
    conn.commit()

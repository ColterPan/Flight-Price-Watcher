"""Thin data-access functions for the fare/watch/alert tables.

Plain sqlite3 + explicit functions rather than an ORM: the schema is four
small tables, and this is simpler to unit test against an in-memory database.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal

from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.models.watch import WatchedRoute, WatchedRouteCreate

#: Two fares for the same route are treated as the same observation if they
#: arrive within this window at the same price from the same site. Without it,
#: every repeat search appends another identical row and the price history
#: becomes mostly duplicates.
_DUPLICATE_WINDOW_MINUTES = 30


def _date_str(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def insert_fare(
    conn: sqlite3.Connection,
    fare: FareResult,
    watched_route_id: int | None = None,
    adults: int = 1,
    cabin: str = "economy",
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO fares (
            watched_route_id, origin, destination, depart_date, return_date,
            site, price, currency, deep_link, scraped_at, adults, cabin,
            airline, carrier_code, stops, duration_minutes, depart_time,
            arrive_time, booking_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            adults,
            cabin,
            fare.airline,
            fare.carrier_code,
            fare.stops,
            fare.duration_minutes,
            fare.depart_time,
            fare.arrive_time,
            fare.booking_url,
        ),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def record_search_fares(
    conn: sqlite3.Connection,
    query: SearchQuery,
    fares: list[FareResult],
    watched_route_id: int | None = None,
) -> list[int]:
    """Persist a search's fares for price history, skipping recent duplicates.

    Returns the row id for each stored fare, and `-1` in the position of any
    fare that was recognised as a duplicate and not re-inserted.
    """
    cutoff = (datetime.now() - timedelta(minutes=_DUPLICATE_WINDOW_MINUTES)).isoformat()
    inserted: list[int] = []
    for fare in fares:
        existing = conn.execute(
            """
            SELECT id FROM fares
            WHERE origin = ? AND destination = ? AND depart_date = ?
              AND (return_date IS ? OR return_date = ?)
              AND adults = ? AND cabin = ? AND site = ? AND price = ?
              AND (depart_time IS ? OR depart_time = ?)
              AND scraped_at >= ?
            LIMIT 1
            """,
            (
                fare.origin,
                fare.destination,
                _date_str(fare.depart_date),
                _date_str(fare.return_date),
                _date_str(fare.return_date),
                query.adults,
                query.cabin,
                fare.site,
                float(fare.price),
                fare.depart_time,
                fare.depart_time,
                cutoff,
            ),
        ).fetchone()
        if existing is not None:
            inserted.append(-1)
            continue
        inserted.append(
            insert_fare(
                conn,
                fare,
                watched_route_id=watched_route_id,
                adults=query.adults,
                cabin=query.cabin,
            )
        )
    return inserted


def get_historical_min(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
    adults: int = 1,
    cabin: str = "economy",
) -> Decimal | None:
    """The lowest price ever recorded for this route *under the same options*.

    Scoped by `adults` and `cabin` because comparing across them is meaningless
    - a 1-passenger economy fare is always "lower" than the 2-passenger
    business fare a watch is actually tracking, which would suppress every
    genuine alert.
    """
    row = conn.execute(
        """
        SELECT MIN(price) AS min_price FROM fares
        WHERE origin = ? AND destination = ? AND depart_date = ?
          AND (return_date IS ? OR return_date = ?)
          AND adults = ? AND cabin = ?
        """,
        (
            origin,
            destination,
            _date_str(depart_date),
            _date_str(return_date),
            _date_str(return_date),
            adults,
            cabin,
        ),
    ).fetchone()
    if row is None or row["min_price"] is None:
        return None
    return Decimal(str(row["min_price"]))


def get_price_history(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
    adults: int = 1,
    cabin: str = "economy",
    limit: int = 500,
) -> list[dict]:
    """The cheapest fare seen per observation time, oldest first.

    One point per scrape rather than per fare, which is what a price chart
    wants: a search returning 32 fares is one observation of "the cheapest
    available", not 32 data points.
    """
    rows = conn.execute(
        """
        SELECT
            MIN(price) AS price,
            scraped_at,
            currency
        FROM fares
        WHERE origin = ? AND destination = ? AND depart_date = ?
          AND (return_date IS ? OR return_date = ?)
          AND adults = ? AND cabin = ?
        GROUP BY scraped_at
        ORDER BY scraped_at DESC
        LIMIT ?
        """,
        (
            origin,
            destination,
            _date_str(depart_date),
            _date_str(return_date),
            _date_str(return_date),
            adults,
            cabin,
            limit,
        ),
    ).fetchall()
    return [
        {
            "price": float(row["price"]),
            "currency": row["currency"],
            "observed_at": row["scraped_at"],
        }
        for row in reversed(rows)
    ]


def create_watch(conn: sqlite3.Connection, watch: WatchedRouteCreate) -> WatchedRoute:
    """Create a watch, or revive and update a previously removed identical one.

    Removal is a soft delete (`is_active = 0`) so historical fares keep their
    foreign key. Combined with the UNIQUE index that means a plain INSERT of a
    route the user removed earlier fails forever with a duplicate-key error -
    so re-adding one reactivates the existing row instead.
    """
    existing = conn.execute(
        """
        SELECT * FROM watched_routes
        WHERE origin = ? AND destination = ? AND depart_date = ?
          AND COALESCE(return_date, '') = COALESCE(?, '')
          AND adults = ? AND cabin = ?
        """,
        (
            watch.origin,
            watch.destination,
            _date_str(watch.depart_date),
            _date_str(watch.return_date),
            watch.adults,
            watch.cabin,
        ),
    ).fetchone()

    if existing is not None:
        if existing["is_active"]:
            raise sqlite3.IntegrityError("watch already exists and is active")
        conn.execute(
            """
            UPDATE watched_routes
            SET is_active = 1, target_price = ?, alert_email = ?, max_stops = ?,
                currency = ?
            WHERE id = ?
            """,
            (
                float(watch.target_price) if watch.target_price is not None else None,
                watch.alert_email,
                watch.max_stops,
                watch.currency,
                existing["id"],
            ),
        )
        conn.commit()
        return get_watch(conn, existing["id"])  # type: ignore[return-value]

    cursor = conn.execute(
        """
        INSERT INTO watched_routes (
            origin, destination, depart_date, return_date, target_price,
            currency, alert_email, is_active, created_at, adults, cabin, max_stops
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            watch.origin,
            watch.destination,
            _date_str(watch.depart_date),
            _date_str(watch.return_date),
            float(watch.target_price) if watch.target_price is not None else None,
            watch.currency,
            watch.alert_email,
            datetime.now().isoformat(),
            watch.adults,
            watch.cabin,
            watch.max_stops,
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
        target_price=_decimal(row["target_price"]),
        currency=row["currency"],
        alert_email=row["alert_email"],
        is_active=bool(row["is_active"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        adults=row["adults"],
        cabin=row["cabin"],
        max_stops=row["max_stops"],
        last_checked_at=(
            datetime.fromisoformat(row["last_checked_at"]) if row["last_checked_at"] else None
        ),
        last_status=row["last_status"],
        last_price=_decimal(row["last_price"]),
    )


def get_watch(conn: sqlite3.Connection, watch_id: int) -> WatchedRoute | None:
    row = conn.execute("SELECT * FROM watched_routes WHERE id = ?", (watch_id,)).fetchone()
    return _row_to_watch(row) if row else None


def list_active_watches(conn: sqlite3.Connection) -> list[WatchedRoute]:
    rows = conn.execute("SELECT * FROM watched_routes WHERE is_active = 1").fetchall()
    return [_row_to_watch(row) for row in rows]


def list_all_watches(conn: sqlite3.Connection) -> list[WatchedRoute]:
    """Active watches, newest first. Soft-deleted rows are not listed.

    A removed watch is kept in the table only so its fare history keeps a valid
    foreign key - it is not something the user should still see.
    """
    rows = conn.execute(
        "SELECT * FROM watched_routes WHERE is_active = 1 ORDER BY created_at DESC"
    ).fetchall()
    return [_row_to_watch(row) for row in rows]


def deactivate_watch(conn: sqlite3.Connection, watch_id: int) -> None:
    conn.execute("UPDATE watched_routes SET is_active = 0 WHERE id = ?", (watch_id,))
    conn.commit()


def update_watch_check_result(
    conn: sqlite3.Connection,
    watch_id: int,
    status: str,
    cheapest_price: Decimal | None,
) -> None:
    """Record the outcome of a background check, for display on the watch list."""
    conn.execute(
        """
        UPDATE watched_routes
        SET last_checked_at = ?, last_status = ?, last_price = ?
        WHERE id = ?
        """,
        (
            datetime.now().isoformat(),
            status,
            float(cheapest_price) if cheapest_price is not None else None,
            watch_id,
        ),
    )
    conn.commit()


def record_alert(conn: sqlite3.Connection, watched_route_id: int, fare_id: int) -> None:
    conn.execute(
        "INSERT INTO alert_log (watched_route_id, fare_id, sent_at) VALUES (?, ?, ?)",
        (watched_route_id, fare_id, datetime.now().isoformat()),
    )
    conn.commit()


def count_alerts_for_watch(conn: sqlite3.Connection, watched_route_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM alert_log WHERE watched_route_id = ?",
        (watched_route_id,),
    ).fetchone()
    return int(row["total"]) if row else 0


def record_scrape_health(
    conn: sqlite3.Connection, site: str, status: str, detail: str | None
) -> None:
    conn.execute(
        "INSERT INTO scrape_health (site, checked_at, status, detail) VALUES (?, ?, ?, ?)",
        (site, datetime.now().isoformat(), status, detail),
    )
    conn.commit()


def latest_scrape_health(conn: sqlite3.Connection) -> list[dict]:
    """The most recent recorded status per site, for the health endpoint.

    Ordered by `id` (strictly increasing on insert) rather than `checked_at`:
    two checks of the same site can be recorded close enough together that
    `datetime.now().isoformat()` produces the same string twice on a clock
    with coarse resolution, which would make "the most recent row" ambiguous
    under a MAX(checked_at) GROUP BY.
    """
    rows = conn.execute(
        """
        SELECT site, status, detail, checked_at
        FROM scrape_health
        WHERE id IN (SELECT MAX(id) FROM scrape_health GROUP BY site)
        ORDER BY site
        """
    ).fetchall()
    return [
        {
            "site": row["site"],
            "status": row["status"],
            "detail": row["detail"],
            "checked_at": row["checked_at"],
        }
        for row in rows
    ]

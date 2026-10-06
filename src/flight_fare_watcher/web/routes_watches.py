"""CRUD, manual re-check and price history for saved watched routes."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from flight_fare_watcher.config import get_settings
from flight_fare_watcher.db import repository
from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.watch import WatchedRoute, WatchedRouteCreate
from flight_fare_watcher.scheduler.jobs import check_watch
from flight_fare_watcher.web.deps import get_db

logger = get_logger(__name__)

router = APIRouter()


@router.post("/api/watches", response_model=WatchedRoute, status_code=201)
def create_watch(
    request: WatchedRouteCreate, conn: sqlite3.Connection = Depends(get_db)
) -> WatchedRoute:
    try:
        return repository.create_watch(conn, request)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="You are already watching this route with these options.",
        ) from exc


@router.get("/api/watches", response_model=list[WatchedRoute])
def list_watches(conn: sqlite3.Connection = Depends(get_db)) -> list[WatchedRoute]:
    return repository.list_all_watches(conn)


@router.delete("/api/watches/{watch_id}", status_code=204)
def delete_watch(watch_id: int, conn: sqlite3.Connection = Depends(get_db)) -> None:
    watch = repository.get_watch(conn, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    repository.deactivate_watch(conn, watch_id)


@router.post("/api/watches/{watch_id}/check")
async def check_watch_now(watch_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Run a watch's check immediately instead of waiting for the scheduler.

    Without this, verifying that a watch works at all means waiting up to
    `CHECK_INTERVAL_HOURS`, which makes the whole alerting path untestable by
    hand.
    """
    watch = repository.get_watch(conn, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")

    try:
        cheapest = await check_watch(conn, watch, get_settings())
    except Exception as exc:  # noqa: BLE001 - report the failure, do not 500 blindly
        logger.exception("manual check of watch %s failed", watch_id)
        raise HTTPException(status_code=502, detail=f"Check failed: {exc}") from exc

    updated = repository.get_watch(conn, watch_id)
    return {
        "watch_id": watch_id,
        "cheapest_price": str(cheapest) if cheapest is not None else None,
        "status": updated.last_status if updated else None,
        "checked_at": updated.last_checked_at.isoformat()
        if updated and updated.last_checked_at
        else None,
    }


@router.get("/api/watches/{watch_id}/history")
def watch_history(watch_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """The recorded cheapest-price-over-time series for a watch's route."""
    watch = repository.get_watch(conn, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")

    points = repository.get_price_history(
        conn,
        watch.origin,
        watch.destination,
        watch.depart_date,
        watch.return_date,
        adults=watch.adults,
        cabin=watch.cabin,
    )
    historical_min = repository.get_historical_min(
        conn,
        watch.origin,
        watch.destination,
        watch.depart_date,
        watch.return_date,
        adults=watch.adults,
        cabin=watch.cabin,
    )
    return {
        "watch_id": watch_id,
        "route": f"{watch.origin}-{watch.destination}",
        "points": points,
        "historical_min": str(historical_min) if historical_min is not None else None,
        "alerts_sent": repository.count_alerts_for_watch(conn, watch_id),
    }

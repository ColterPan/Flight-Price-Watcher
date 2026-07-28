"""CRUD endpoints for saved watched routes."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from flight_fare_watcher.db import repository
from flight_fare_watcher.models.watch import WatchedRoute, WatchedRouteCreate
from flight_fare_watcher.web.deps import get_db

router = APIRouter()


@router.post("/api/watches", response_model=WatchedRoute, status_code=201)
def create_watch(request: WatchedRouteCreate, conn: sqlite3.Connection = Depends(get_db)) -> WatchedRoute:
    try:
        return repository.create_watch(conn, request)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="a watch for this exact route and dates already exists") from exc


@router.get("/api/watches", response_model=list[WatchedRoute])
def list_watches(conn: sqlite3.Connection = Depends(get_db)) -> list[WatchedRoute]:
    return repository.list_all_watches(conn)


@router.delete("/api/watches/{watch_id}", status_code=204)
def delete_watch(watch_id: int, conn: sqlite3.Connection = Depends(get_db)) -> None:
    watch = repository.get_watch(conn, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    repository.deactivate_watch(conn, watch_id)

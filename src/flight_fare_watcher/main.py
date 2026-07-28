"""Entrypoint: `uvicorn flight_fare_watcher.main:app`."""

from __future__ import annotations

from flight_fare_watcher.web.app import app

__all__ = ["app"]

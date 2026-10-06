"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from flight_fare_watcher.config import get_settings
from flight_fare_watcher.currency import ExchangeRateCache
from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.scheduler.jobs import run_watch_check_job
from flight_fare_watcher.search.cache import SearchCache
from flight_fare_watcher.web import (
    routes_currency,
    routes_health,
    routes_pages,
    routes_search,
    routes_watches,
)

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.search_cache = SearchCache(settings.search_cache_ttl_seconds)
    app.state.exchange_rate_cache = ExchangeRateCache(settings.exchange_rate_cache_ttl_seconds)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_watch_check_job,
        trigger="interval",
        hours=settings.check_interval_hours,
        args=[settings.database_path, settings],
        id="watch_check",
        replace_existing=True,
        # A long scrape must not cause overlapping runs to pile up.
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "started with providers=%s, watch check every %sh",
        settings.enabled_site_list,
        settings.check_interval_hours,
    )
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Flight Fare Watcher", lifespan=lifespan)
    # These caches are also attached here so an app built without running its
    # lifespan (as TestClient does for simple unit tests) still works.
    settings = get_settings()
    app.state.search_cache = SearchCache(settings.search_cache_ttl_seconds)
    app.state.exchange_rate_cache = ExchangeRateCache(settings.exchange_rate_cache_ttl_seconds)

    app.include_router(routes_pages.router)
    app.include_router(routes_search.router)
    app.include_router(routes_watches.router)
    app.include_router(routes_health.router)
    app.include_router(routes_currency.router)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()

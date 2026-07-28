"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from flight_fare_watcher.config import get_settings
from flight_fare_watcher.scheduler.jobs import run_watch_check_job
from flight_fare_watcher.web import routes_pages, routes_search, routes_watches

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_watch_check_job,
        trigger="interval",
        hours=settings.check_interval_hours,
        args=[settings.database_path, settings],
        id="watch_check",
        replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Flight Fare Watcher", lifespan=lifespan)
    app.include_router(routes_pages.router)
    app.include_router(routes_search.router)
    app.include_router(routes_watches.router)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()

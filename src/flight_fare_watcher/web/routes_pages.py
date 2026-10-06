"""Server-rendered HTML pages (search page, watches management page)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from flight_fare_watcher.models.search import CABIN_LABELS

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

#: A sensible default so the date picker does not open on today (same-day
#: domestic fares are usually the most expensive on the chart).
DEFAULT_DEPART_OFFSET_DAYS = 30


@router.get("/")
def index(request: Request):
    default_depart = date.today() + timedelta(days=DEFAULT_DEPART_OFFSET_DAYS)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_page": "search",
            "default_depart_date": default_depart.isoformat(),
            "min_date": date.today().isoformat(),
            "cabin_labels": CABIN_LABELS,
        },
    )


@router.get("/watches")
def watches_page(request: Request):
    return templates.TemplateResponse(
        request,
        "watches.html",
        {
            "active_page": "watches",
            "min_date": date.today().isoformat(),
            "cabin_labels": CABIN_LABELS,
        },
    )

"""Server-rendered HTML pages (search page, watches management page)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/watches")
def watches_page(request: Request):
    return templates.TemplateResponse(request, "watches.html", {})

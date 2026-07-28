# Flight Fare Watcher

A personal, locally-run tool that searches a small set of flight booking
sites for a given route, shows you the cheapest fare it finds with a link to
buy it, and can watch a saved route in the background and email you when the
price drops.

> **This is not a Skyscanner clone.** It scrapes two sites (Google Flights and
> Kiwi.com) with Playwright — it does not aggregate "every site," and it does
> not use any flight-data APIs. See [Limitations & Terms of Service](#limitations--terms-of-service)
> before using it.

## Status

Under active development. See [docs/architecture.md](docs/architecture.md)
for the current design and build phases.

## Overview

- **On-demand search**: enter an origin, destination, and dates; the tool
  searches Google Flights and Kiwi.com concurrently and returns the cheapest
  fares found, each with a deep link to the site where you'd actually buy the
  ticket.
- **Watch & alert**: save a route with a target price. A background job
  re-checks it periodically (default every 4 hours) and emails you when a new
  low fare appears at or below your target.
- **Local only**: runs on your own machine via `uvicorn`. Nothing is hosted,
  nothing is multi-user.

## Install

Requirements: Python 3.11+, Windows/macOS/Linux.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -e ".[dev]"
playwright install chromium

copy .env.example .env          # Windows
# cp .env.example .env          # macOS/Linux
# then edit .env with your real SMTP credentials
```

## Usage

```bash
uvicorn flight_fare_watcher.main:app
```

Then open http://127.0.0.1:8000 in a browser to search for flights or manage
watched routes.

> **Windows: do not add `--reload`.** Uvicorn's `--reload` runs the server
> under a subprocess-based file-watcher, and on Windows it deliberately
> switches to `asyncio`'s `SelectorEventLoop` to make that work. Playwright
> needs to launch the browser as a subprocess, which `SelectorEventLoop`
> cannot do on Windows (`ProactorEventLoop` can) - so any search will fail
> with `NotImplementedError` if `--reload` is used. This doesn't affect
> macOS/Linux. Since this is a local tool you run once and leave running,
> `--reload` isn't needed anyway; just restart the command after editing code.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full design:
scraper adapters, the search orchestrator, the watch/alert scheduler, and the
data model.

## Testing

```bash
pytest
```

Unit and integration tests run against mocked scrapers and an in-memory
database — no live network access, so they're safe to run repeatedly and in
CI. A separate `tests/live_smoke/` suite exists for manually verifying a real
site still scrapes correctly; it is **not** run automatically. See
[docs/architecture.md](docs/architecture.md#testing) for details.

## Limitations & Terms of Service

This tool works by automating a browser (Playwright) to load public pages on
third-party websites and read the fares those pages display. That commonly
conflicts with those sites' Terms of Service, which typically prohibit
automated access. This project is intended strictly for **personal,
non-commercial, low-frequency, educational use** by whoever runs it — not for
redistribution, not for hosting as a service, and not for high-frequency or
bulk use. Anyone using this code is responsible for how they use it.

Scraper adapters will break when a target site changes its page structure.
This is treated as an expected condition, not a bug: the tool distinguishes
"no flights found" from "the scraper appears to be blocked or the page
structure changed" in its logs and UI, rather than silently returning wrong
data.

## License

[MIT](LICENSE) — covers the code only, not permission to violate any third
party's Terms of Service.

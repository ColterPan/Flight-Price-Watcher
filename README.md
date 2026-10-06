# Flight Fare Watcher

A personal, locally-run tool that searches for flights across multiple fare
sources, shows you the cheapest ones with a link to buy the exact flight you
picked, and can watch a saved route in the background and email you when the
price drops.

> **This is not a Skyscanner clone.** One of its three fare sources (Google
> Flights) works by scraping a real page with Playwright — it does not
> aggregate "every site." See [Limitations & Terms of Service](#limitations--terms-of-service)
> before using it.

## Overview

- **On-demand search**: enter an origin, destination, dates, passenger count,
  cabin, and a stops limit. The tool queries every enabled fare source
  concurrently and returns the cheapest results, each showing real itinerary
  detail (times, duration, stops, layovers, bags) rather than a bare price.
- **A real link to the flight you picked** - not just a link back to a search
  page. For the cheapest few results this is resolved automatically; any other
  result can get one on demand with "Get direct link."
- **Three fare providers**, mix and match via `ENABLED_SITES`:
  - `google_flights` - live prices scraped from the real site (Playwright).
  - `amadeus` - the [Amadeus Self-Service Flight Offers Search API](https://developers.amadeus.com)
    (free tier available; set `AMADEUS_API_KEY`/`AMADEUS_API_SECRET`).
  - `demo` - deterministic synthetic fares with no network or browser at all,
    useful for trying the whole app with zero setup.
- **Watch & alert**: save a route (with passengers/cabin/stops options) and an
  optional target price. A background job re-checks it periodically (default
  every 4 hours) and emails you when a new low fare appears at or below your
  target. Use "Check now" to test a watch immediately instead of waiting, and
  "Show price history" for a quick chart of what it has seen.
- **Airport autocomplete**: type a city name, pick the airport - no need to
  already know IATA codes.
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
# then edit .env - see "Configuration" below
```

## Configuration

Edit `.env` (see `.env.example` for every option with comments). The only
provider enabled by default is `google_flights`, which needs no API key.

- **Try it with zero setup**: set `ENABLED_SITES=demo` to use synthetic fares,
  or `ENABLED_SITES=demo,google_flights` to see both side by side.
- **Email alerts**: fill in `SMTP_*`/`ALERT_*` to let watches actually send
  mail. Without this, watches still track price history and the UI still
  shows what they found - they just can't notify you.
- **Amadeus**: add `amadeus` to `ENABLED_SITES` and set
  `AMADEUS_API_KEY`/`AMADEUS_API_SECRET` (free tier at
  [developers.amadeus.com](https://developers.amadeus.com)). Until configured
  it reports its status as "not set up" rather than failing.

## Usage

```bash
uvicorn flight_fare_watcher.main:app
```

Then open <http://127.0.0.1:8000> in a browser to search for flights or manage
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

See [docs/architecture.md](docs/architecture.md) for the full design: the
provider contract, the search orchestrator and its result cache, booking-link
resolution, the watch/alert scheduler, and the data model.

## Testing

```bash
pytest
```

Unit and integration tests run against mocked providers and an in-memory
database — no live network access, so they're safe to run repeatedly and in
CI. A separate `tests/live_smoke/` suite exists for manually verifying the
real Google Flights site still scrapes (and books) correctly; it is **not**
run automatically. See [docs/architecture.md](docs/architecture.md#testing)
for details.

## Limitations & Terms of Service

The `google_flights` provider works by automating a browser (Playwright) to
load public pages on a third-party website and read the fares that page
displays. That commonly conflicts with that site's Terms of Service, which
typically prohibits automated access. This project is intended strictly for
**personal, non-commercial, low-frequency, educational use** by whoever runs
it — not for redistribution, not for hosting as a service, and not for
high-frequency or bulk use. Anyone using this code is responsible for how
they use it. The `amadeus` and `demo` providers do not scrape anything.

The Google Flights adapter will break when the site changes its page
structure. This is treated as an expected condition, not a bug: the tool
distinguishes "no flights found" from "the provider appears to be blocked or
the page structure changed" from "this provider isn't configured" in its logs
and UI, rather than silently returning wrong data. See
[docs/recon_notes.md](docs/recon_notes.md) for what the parser is built
against and `scripts/capture_google_flights_fixture.py` to re-verify it.

## License

[MIT](LICENSE) — covers the code only, not permission to violate any third
party's Terms of Service.

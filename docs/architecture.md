# Architecture

## Scope

This is a personal, local flight-fare search and price-drop-alert tool. It
scrapes **Google Flights only** in v1 (see [recon_notes.md](recon_notes.md)
for why Kiwi.com was investigated but not shipped). It is not a meta-search
engine and does not use any flight-data API.

## Request flow: on-demand search

```
Browser (index.html + app.js)
  -> POST /api/search {origin, destination, depart_date, return_date}
  -> web/routes_search.py
       -> scrapers/registry.py: build enabled adapters from ENABLED_SITES
       -> search/orchestrator.py: run_search()
            - launches one Playwright Chromium instance
            - one BrowserContext per adapter (isolated cookies/state)
            - runs all adapters concurrently via asyncio.gather
            - each adapter catches its own exceptions -> ScrapeOutcome
            - aggregates fares (sorted ascending by price) + per-site status
       -> every returned fare is opportunistically written to the `fares`
          table (builds price history even without a saved watch)
  <- SearchResponse {fares: [...], site_statuses: {site: status}}
```

Per-site status (`ok` / `no_results` / `blocked_or_structure_changed` /
`error`) is always returned, even when some sites fail - the UI shows this so
a blocked scraper is visibly distinct from "no flights found," never silently
hidden.

## Request flow: watch / alert

```
Browser (watches.html + app.js)
  -> POST /api/watches {origin, destination, dates, target_price?, alert_email?}
  -> web/routes_watches.py -> db/repository.py: create_watch()
     (UNIQUE index on origin+destination+depart_date+COALESCE(return_date,'')
      prevents duplicate watches, including one-way routes)

Background (in-process APScheduler, started in web/app.py's FastAPI lifespan):
  every CHECK_INTERVAL_HOURS:
    scheduler/jobs.py: run_watch_check_job()
      for each active watch:
        check_watch():
          - read historical min price for this route from `fares`
          - run_search() (same orchestrator as on-demand search)
          - record per-site scrape_health rows
          - persist every returned fare (watched_route_id = this watch)
          - alerts/threshold.py: meets_alert_criteria(cheapest, target, historical_min)
              -> new all-time low, and at/below target if one is set
          - if met: alerts/mailer.py sends an email via smtplib,
            alert_log row recorded (so re-checks don't need to guess whether
            an alert was already sent for a given fare)
          - one watch's failure is caught and logged; the loop continues to
            the next watch rather than aborting the whole run
```

## Why no ORM, no external scheduler, no JS framework

- **Raw `sqlite3` + a `repository.py`** of explicit functions: four small
  tables. An ORM would add a dependency and an abstraction layer for no real
  benefit at this size, and raw SQL is easy to unit test against an in-memory
  database.
- **APScheduler running in-process** (inside the same FastAPI app, started in
  its `lifespan`): no dependency on Windows Task Scheduler or cron, so the
  whole tool is "run one command, everything works," which matters for a
  local single-user tool.
- **Server-rendered Jinja2 + vanilla JS**: no bundler, no second package
  ecosystem, no build step. Two pages and a few dozen lines of fetch-based JS
  is all this needs.

## Scraper adapter contract

Every site adapter implements `FlightSiteAdapter.search(...) -> ScrapeOutcome`
(`scrapers/base.py`). Rules every adapter follows:

1. **Never let an exception escape.** Catch everything internally and return
   `ScrapeOutcome(status="error", ...)`. The orchestrator also has a
   defensive backstop for this, but each adapter is expected to enforce it.
2. **Distinguish "no results" from "blocked/broken."** Zero results with a
   page that still looks like a normal results page is `no_results`. Zero
   results (or zero *parseable* results) on a page that doesn't look right is
   `blocked_or_structure_changed`. Conflating these would mean the tool could
   silently tell you "no flights exist" when it's actually just broken.
3. **Realistic browser fingerprint, not evasion infrastructure.** See
   `scrapers/base.py::new_context()` - a normal desktop viewport/user-agent/
   locale, nothing more. No proxy rotation, no CAPTCHA solving. If a site
   starts reliably blocking even at low frequency with this configuration,
   the answer is to disable it via `ENABLED_SITES`, not to escalate evasion.
4. **Pure parsing, separate from navigation.** Each adapter's row-parsing
   logic (e.g. `google_flights.py::parse_flight_row`) is a plain function
   over text, tested against real captured fixtures in
   `tests/fixtures/sample_html/` with zero network/browser dependency.

Adding a new site means: write one adapter file implementing this contract,
register it in `scrapers/registry.py`, and add it to `ENABLED_SITES`. Nothing
else changes.

## Testing

- `pytest` (no args) runs only `tests/unit` and `tests/integration` (see
  `pyproject.toml` `testpaths`) - fully offline, no browser launch, safe for
  CI and safe to run repeatedly without touching any real site.
- `tests/live_smoke/` is excluded from that default run and from CI. Run it
  by hand (`pytest tests/live_smoke -v -s`) when you suspect Google Flights
  changed its page structure and the adapter needs fixing.
- `docs/recon_notes.md` records exactly what selectors/behavior each adapter
  was built against and when it was last verified - update it whenever you
  fix a broken adapter.

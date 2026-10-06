# Architecture

## Scope

This is a personal, local flight-fare search and price-drop-alert tool. It
has three fare **providers** (`scrapers/registry.py`), selected per-deployment
via `ENABLED_SITES`:

- `google_flights` - Playwright browser automation against the real site.
- `amadeus` - the Amadeus Self-Service Flight Offers Search API (optional,
  needs credentials; see `scrapers/amadeus_api.py`).
- `demo` - deterministic synthetic fares, no network or browser at all.

It is not a meta-search engine in the commercial sense - no API aggregates
"every site," and the browser-based provider works by rendering real pages,
which carries the Terms-of-Service caveats in the README.

## Request flow: on-demand search

```
Browser (index.html + search.js)
  -> POST /api/search {origin, destination, depart_date, return_date,
                        adults, cabin, max_stops, refresh}
  -> web/routes_search.py
       -> SearchQuery validates the request (IATA codes, no past/absurd
          dates, return >= depart - see models/search.py)
       -> search/cache.py: an identical query within SEARCH_CACHE_TTL_SECONDS
          is served from memory instead of re-running every provider
          (skipped entirely when `refresh: true` is sent)
       -> scrapers/registry.py: build_adapters_from_settings() from
          ENABLED_SITES (+ Amadeus credentials, if configured)
       -> search/orchestrator.py: run_search()
            - browser launched only if at least one enabled provider
              needs one (FlightSiteAdapter.needs_browser)
            - one BrowserContext per browser-based provider (isolated
              cookies/state); API-based providers run without one
            - runs every provider concurrently via asyncio.gather
            - each provider catches its own exceptions -> ScrapeOutcome
            - aggregates fares (sorted ascending by price) + per-site status
              + per-site diagnostic text
            - resolves a per-flight booking link for the cheapest
              BOOKING_LINK_RESOLVE_COUNT fares (0 by default cost is ~8-15s
              per fare; any other fare can still be resolved on demand)
       -> every returned fare is opportunistically written to the `fares`
          table, deduplicated against the last 30 minutes of identical
          observations (builds price history even without a saved watch)
  <- SearchResponse {fares: [...], site_statuses: {...}, site_diagnostics: {...},
                      from_cache}
```

Per-site status (`ok` / `no_results` / `blocked_or_structure_changed` /
`not_configured` / `error`) is always returned, even when some providers
fail - the UI shows this so a blocked scraper, an unconfigured API, and "no
flights exist" are three visibly different things, never silently conflated.

### Booking links

A plain search result links to a search page, not a specific flight. For
Google Flights, `scrapers/google_flights_booking.py` clicks through to a
per-itinerary URL (`/travel/flights/booking?tfs=...`) that is shareable and
not time-limited - see `docs/recon_notes.md` for how that was found and why a
deeper click-through to the airline's own checkout is deliberately not used.
Matching a chosen `FareResult` back to a row on a fresh page load is done on
parsed itinerary data (price, times, stops), not row position, since the page
lists "best" picks before the full sorted list. `POST /api/booking-link`
exposes this on demand for any fare the automatic resolution during search
didn't cover.

## Request flow: watch / alert

```
Browser (watches.html + watches.js)
  -> POST /api/watches {origin, destination, dates, adults, cabin,
                         max_stops, target_price?, alert_email?}
  -> web/routes_watches.py -> db/repository.py: create_watch()
     (UNIQUE index on origin+destination+depart_date+COALESCE(return_date,'')
      +adults+cabin - re-adding a route you previously removed reactivates
      the existing soft-deleted row instead of hitting a duplicate-key error)

POST /api/watches/{id}/check  - run one watch's check immediately (same
  check_watch() the scheduler uses), so a watch can be verified without
  waiting for CHECK_INTERVAL_HOURS.

GET /api/watches/{id}/history - the recorded cheapest-price-per-scrape
  series for that watch's exact route+options, for the UI's sparkline.

Background (in-process APScheduler, started in web/app.py's FastAPI lifespan):
  every CHECK_INTERVAL_HOURS:
    scheduler/jobs.py: run_watch_check_job()
      for each active watch:
        check_watch():
          - build this watch's SearchQuery (its saved adults/cabin/max_stops)
          - read historical min price for this *exact* route+adults+cabin
            from `fares` (scoped so a cheap 1-adult economy fare never looks
            like a price drop on a 2-adult business watch)
          - run_search() (same orchestrator as on-demand search)
          - record per-site scrape_health rows
          - persist every returned fare (watched_route_id = this watch)
          - update_watch_check_result(): last_status/last_price/
            last_checked_at on the watch itself, so the UI shows this
            without re-deriving it from `fares`
          - alerts/threshold.py: meets_alert_criteria(cheapest, target, historical_min)
              -> new all-time low, and at/below target if one is set
          - if met: alerts/mailer.py sends an email via smtplib. A failed
            send (bad SMTP config, network hiccup) is caught and logged -
            it must not look like "the search failed," since fares were
            genuinely found and already persisted by this point
          - alert_log row recorded only on an actually-sent email (so
            re-checks don't need to guess whether an alert already went out)
          - one watch's failure is caught and logged as last_status="error";
            the loop continues to the next watch rather than aborting the run
```

## Why no ORM, no external scheduler, no JS framework

- **Raw `sqlite3` + a `repository.py`** of explicit functions: a handful of
  small tables plus migrations that add columns in place (`db/database.py`)
  rather than a migration framework. An ORM would add a dependency and an
  abstraction layer for no real benefit at this size, and raw SQL is easy to
  unit test against an in-memory database.
- **APScheduler running in-process** (inside the same FastAPI app, started in
  its `lifespan`): no dependency on Windows Task Scheduler or cron, so the
  whole tool is "run one command, everything works," which matters for a
  local single-user tool.
- **Server-rendered Jinja2 + vanilla JS**: no bundler, no second package
  ecosystem, no build step. A few hundred lines of fetch-based JS, split by
  page (`app.js` shared helpers, `search.js`, `watches.js`), is all this
  needs.
- **An in-process `SearchCache`** (`search/cache.py`) rather than Redis or
  similar: a single dict behind an `asyncio.Lock`, sized for one user
  iterating on a search. Correct to lose on restart, since fares go stale.

## Provider contract

Every provider implements `FlightSiteAdapter` (`scrapers/base.py`):

```python
async def search(self, query: SearchQuery, context: BrowserContext | None) -> ScrapeOutcome
async def resolve_booking_url(self, query, fare, context) -> str | None  # optional, defaults to None
needs_browser: bool  # False skips BrowserContext setup entirely for this provider
```

Rules every provider follows:

1. **Never let an exception escape `search`.** Catch everything internally and
   return `ScrapeOutcome(status="error", ...)`. The orchestrator also has a
   defensive backstop for this, but each provider is expected to enforce it
   itself.
2. **Distinguish "no results" from "blocked/broken" from "not configured."**
   Zero results on a page/response that still looks normal is `no_results`.
   Zero results (or zero *parseable* results) on something that doesn't look
   right is `blocked_or_structure_changed`. A provider that needs credentials
   it wasn't given reports `not_configured`, not `error` - a missing optional
   integration is not a failure. Conflating any of these would mean the tool
   could silently tell you "no flights exist" when it's actually broken or
   unset up.
3. **Realistic browser fingerprint, not evasion infrastructure** (browser
   providers only). See `scrapers/base.py::new_context()` - a normal desktop
   viewport/user-agent/locale, nothing more. No proxy rotation, no CAPTCHA
   solving. If a site starts reliably blocking even at low frequency with this
   configuration, the answer is to disable it via `ENABLED_SITES`, not to
   escalate evasion.
4. **Pure parsing, separate from navigation.** Each provider's parsing logic
   (e.g. `google_flights_parse.py::parse_aria_label`,
   `amadeus_api.py::parse_offer`) is a plain function over data, tested
   against real captured fixtures with zero network/browser dependency.

Adding a new provider means: write one adapter file implementing this
contract, register it in `scrapers/registry.py`, and add it to
`ENABLED_SITES`. Nothing else changes.

## Testing

- `pytest` (no args) runs only `tests/unit` and `tests/integration` (see
  `pyproject.toml` `testpaths`) - fully offline, no browser launch, safe for
  CI and safe to run repeatedly without touching any real site.
- `tests/live_smoke/` is excluded from that default run and from CI. Run it
  by hand (`pytest tests/live_smoke -v -s`) when you suspect Google Flights
  changed its page structure and the adapter needs fixing.
- `docs/recon_notes.md` records exactly what selectors/behavior each provider
  was built against and when it was last verified - update it whenever you
  fix a broken adapter. `scripts/capture_google_flights_fixture.py`
  re-captures the real-row fixtures that `test_google_flights_parser.py`
  tests against.

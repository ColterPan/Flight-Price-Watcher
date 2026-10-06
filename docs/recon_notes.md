# Recon Notes

Findings from the manual/scripted reconnaissance spike (Phase 1), used to build
the scraper adapters without inventing selectors. Update this file with a new
dated entry whenever an adapter breaks and gets fixed.

## Google Flights — verified working, last verified 2026-10-06

**v2 update (this entry)**: the v1 parser (innerText + regex) and the v1 deep
link (always the search URL) were both replaced after live recon found they
were producing wrong data. See the dated findings below; the v1 notes further
down are kept for history but no longer describe the current adapter.

**Row duplication (critical, found live)**: `li.pIav2d` matches **two full
copies** of the result list - one visible, one an off-screen mirror whose
`innerText` has accessibility strings inlined (hence the mangled "garbage
airline" values the v1 parser sometimes produced, like
`"on Fri, Nov 20 – 9:22 AM9:22 AMAmerican"`). Measured on JFK→LAX: 64 rows,
32 real. **Fix**: filter to
`row.getBoundingClientRect().height > 0 && row.offsetParent` before parsing
anything. Verified across two routes/shapes (JFK-LAX round trip, BOS-SIN one
way with multi-stop/long-haul rows): the visible-row count is exactly half
the total in every case observed.

**Parse the aria-label, not innerText**: each row's clickable
`div[role="link"]` carries a complete, stable aria-label, e.g.:

```
From 409 US dollars round trip total. Nonstop flight with American. Leaves
John F. Kennedy International Airport at 6:00 AM on Friday, November 20 and
arrives at Los Angeles International Airport at 9:22 AM on Friday, November
20. Total duration 6 hr 22 min.   1 carry-on bag included. 0 checked bags
included.  Select flight
```

A multi-stop long-haul row adds an operating-carrier clause and one
`Layover (N of M) is a <duration> layover at <airport> in <city>.` clause per
stop:

```
From 1211 US dollars. 2 stops flight with American and Finnair. Operated by
Republic as American Eagle for American Airlines. Leaves Boston Logan
International Airport at 5:35 PM on Tuesday, December 15 and arrives at
Singapore Changi Airport at 6:40 PM on Thursday, December 17. Total duration
36 hr 5 min.  Layover (1 of 2) is a 1 hr 17 min layover at Seattle-Tacoma...
```

This is a far better parse target than innerText: it is the accessibility
label (changes less often than minified class names/DOM nesting), and it is
*complete* - one regex grammar recovers price, currency, trip type, stops,
airline(s), operating carrier, both airport names, both clock times, total
duration, every layover (airport/city/duration), and bag allowances, with no
positional-index guessing between nonstop and multi-stop row shapes. Verified:
100% parse rate across all 45 real rows captured from both test routes (see
`scripts/capture_google_flights_fixture.py` and
`tests/unit/test_google_flights_parser.py`).

**Carrier IATA code**: not in the aria-label, but recoverable from the row's
airline-logo CSS: `background-image` references
`airline_logos/70px/AA.png` (or `.../dark/AA.png`) - the 2-3 letter code
before `.png` is the carrier code. Used for `FareResult.carrier_code`.

**Booking link - a real per-itinerary URL exists** (supersedes the v1
"deep link is just the search URL" decision below): clicking a result row's
`div[role="link"]` navigates to
`https://www.google.com/travel/flights/booking?tfs=<base64>&tfu=<base64>&...`,
confirmed shareable (no session token/timestamp) and lands directly on that
flight's "Booking options" panel. The click needs `force=True`: the row's
clickable overlay is covered by its own sibling content, so a normal
Playwright click is refused as "intercepted".

**Round trips need a second click.** The outbound click above does *not*
reach `/booking` for a round trip - it lands on
`/travel/flights/search?tfs=...`, a return-leg-selection step with its own
`li.pIav2d` list (same selector, same visible/mirror duplication). Exactly one
return row carries the same round-trip total price already shown on the
outbound row (verified: of 9 return options for one JFK-LAX search, only 1
matched the $409 total already quoted) - clicking *that* row reaches
`/booking`. One-way searches skip this step. Implemented in
`scrapers/google_flights_booking.py`.

Going one step further and following `Continue` to the airline's own
checkout **was tested and confirmed to work** (landed on a genuine
`jetblue.com/booking/trip-summary?...` URL with real `flightNumbers`/
`fareBasisCode` params) but is deliberately **not** what gets returned:
that URL carries `t=<epoch>`/`sig=<signature>` params (time-limited,
session-tied - dead by the time an emailed alert is read), and the airline
served a bot-detection "Client Challenge" interstitial to the automated
browser immediately afterward anyway. The `/booking` URL has neither problem
and is still one click from checkout.

**Cost**: resolving one booking link is a real page load + click(s), ~8-10s
measured (one-way) to ~10-15s (round trip, two clicks). Not done for every
row of every search - see `BOOKING_LINK_RESOLVE_COUNT` in config and the
on-demand `POST /api/booking-link` endpoint for any other row.

---

### v1 notes (superseded by the above, kept for history)

**Last verified 2026-07-28**, before the row-duplication bug above was found.

**Navigation**: direct URL, no UI interaction needed. This is stable because
it's Google's own shareable-search-link format.

```
https://www.google.com/travel/flights?q=Flights%20from%20{ORIGIN}%20to%20{DEST}%20on%20{YYYY-MM-DD}[%20one%20way]&hl=en&gl=US&curr=USD
```

- Omit `one way` for round trip (requires a second date in the `q` text,
  e.g. `... on 2026-09-01 through 2026-09-05`); include ` one way` for one-way.
- `hl`, `gl`, `curr` pin language/region/currency so parsing doesn't depend on
  the browser's ambient locale.
- No CAPTCHA/challenge encountered when hit at low frequency from a single
  realistic headless Chromium context (see adapter's `new_context()` config).

**Result rows**: after `domcontentloaded` + ~6s settle time, each flight result
is an `<li class="pIav2d">`. Confirmed by DOM query, not by hand-inspecting
minified HTML (Google's HTML is a single giant line; querying the live DOM via
`page.evaluate` is far more reliable than text-searching the serialized HTML).

Row `innerText` looks like:
```
8:30 AM
 – 
11:28 AM
JetBlue
5 hr 58 min
JFK–LAX
Nonstop
416 kg CO2e
+28% emissions
1
0
$351
round trip
```
Parse this by splitting on newlines and pattern-matching known fragments
(times via `\d{1,2}:\d{2} [AP]M`, duration via `\d+ hr \d+ min`, price via
`\$\d[\d,]*`, route via `[A-Z]{3}–[A-Z]{3}`) rather than positional indexing,
since row content varies slightly (e.g. nonstop vs 1-stop rows have an extra
layover-airport field).

**Blocked/challenge detection**: no real CAPTCHA was observed during recon,
so the exact "you've been blocked" DOM signature is unconfirmed. Treat as
`blocked_or_structure_changed` (not `no_results`) whenever, after the settle
wait, zero `li.pIav2d` elements are found **and** the page title/body does not
contain the expected route text — this distinguishes "genuinely no flights"
from "page didn't render as expected."

**Deep link — deliberate v1 scope decision**: Google Flights results don't
expose a plain `<a href>` per row to the final purchase page. The real flow
is: click a result row → (round trip only) select a return flight → a
"Booking options" panel appears with per-airline/OTA price tiles and
`Continue` buttons → clicking `Continue` opens a **new tab** at
`google.com/travel/clk/f?...`, which itself redirects to the real airline
booking URL (confirmed: landed on a genuine `jetblue.com/booking/trip-summary?...`
URL with real flight number/fare basis params).

This works, but chasing it for every result row means 2-3 extra interactive
steps *per fare*, multiplying scrape time and breakage surface by the number
of results shown. **v1 deep link is the Google Flights search-results URL
itself** (the same `?q=...` URL used to find the fare) — the user lands on
the exact search and can pick a booking option same as they would on
Google Flights directly. Following the full click-through chain to link
directly to the airline's own booking page is a documented v2 enhancement,
worth doing only for the single cheapest result (not all rows) if picked up
later.

## Kiwi.com — not built for v1, see reasons below

Attempted both a direct results URL (guessed from Kiwi's own homepage query
params after a real UI search) and the full interactive homepage form flow.
Neither was reliable enough to build an adapter against in good conscience:

1. **Direct result URLs don't reliably hydrate.** Loading
   `kiwi.com/en/search/results/{origin-slug}/{dest-slug}/{dates}` cold shows
   the correct route/dates in the header UI but renders "Nothing here yet...
   A departure and a destination must be filled in to search" — the SPA's
   client state isn't actually populated by the URL alone in the way the
   header text suggests. There may be an additional required query
   parameter this recon didn't identify; not confirmed within a reasonable
   time budget.
2. **A persistent "home airport" default silently attaches to every origin.**
   Every real search attempt via the interactive form — even after
   explicitly clearing the origin field with Ctrl+A/Backspace before typing
   a fresh IATA code — resulted in a combined origin of
   `singapore-singapore,john-f-kennedy-international-...` in the final query
   string. This looks like a stored home-airport preference (likely
   IP-geolocation-derived) that gets bundled into the search independently of
   what the visible form field shows, which is a multi-origin search Kiwi
   supports but that a personal fare-search tool should never silently
   trigger. Clearing it reliably would need finding whatever cookie/
   localStorage/account setting holds it — not done here.
3. **Ambiguous submit control.** The visible "Search"/"Explore" button text
   changes based on form validity, and an equally-labeled top-nav toggle
   ("Search | AI Mode") made `get_by_role("button", name="Search")` matches
   ambiguous; had to disambiguate by geometry, which is itself a sign the
   page isn't structured for reliable automation targeting.

None of this rules Kiwi out forever — it just means it needs a dedicated,
patient reverse-engineering session (likely: inspect network requests directly
via `page.on("request")`/`page.on("response")` to find the real internal
search API call Kiwi's own frontend makes, rather than fighting its rendered
UI). Until then, shipping an adapter against this half-understood state would
mean guessing at exactly the kind of unverified selector/behavior this
project's approach is meant to avoid.

**v1 decision: `ENABLED_SITES` ships with only `google_flights`.** The
`FlightSiteAdapter` interface and registry are unchanged — adding `kiwi` later
is a matter of writing one adapter file and flipping the config, with no
changes needed elsewhere.

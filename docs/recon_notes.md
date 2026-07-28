# Recon Notes

Findings from the manual/scripted reconnaissance spike (Phase 1), used to build
the scraper adapters without inventing selectors. Update this file with a new
dated entry whenever an adapter breaks and gets fixed.

## Google Flights — verified working, last verified 2026-07-28

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

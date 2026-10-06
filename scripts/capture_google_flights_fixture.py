"""Re-capture the Google Flights result-row fixture used by the parser unit tests.

Run this by hand when `tests/unit/test_google_flights_parser.py` starts failing
because Google changed its markup:

    python scripts/capture_google_flights_fixture.py

It writes `tests/fixtures/sample_html/google_flights_rows_v2.json` with, for
each sample route, every `li.pIav2d` row's visibility flag, its
`div[role=link]` aria-label (the parser's primary input) and the carrier code
recovered from the airline-logo CSS. Then update the dated entry in
`docs/recon_notes.md` to say what changed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "sample_html"
    / "google_flights_rows_v2.json"
)

# Deliberately two shapes: a short-haul round trip (mostly nonstop) and a
# long-haul one way (multi-stop, multi-carrier, next-day arrivals), so the
# parser is tested against both aria-label grammars.
CASES = [
    ("JFK", "LAX", "2026-11-20", "2026-11-27"),
    ("BOS", "SIN", "2026-12-15", None),
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
SETTLE_MS = 8000

# Kept in sync with scrapers/google_flights.py::_EXTRACT_ROWS_JS - that module
# is the source of truth; this script only needs the same shape for fixtures.
EXTRACT_JS = r"""() => {
  const rows = [...document.querySelectorAll('li.pIav2d')];
  return {
    title: document.title,
    rows: rows.map((row) => {
      const link = row.querySelector('div[role="link"][aria-label]');
      const logo = row.querySelector('[style*="airline_logos"]');
      let carrier = null;
      if (logo) {
        const match = (logo.getAttribute('style') || '')
          .match(/airline_logos\/[^/]+\/([A-Z0-9]{2,3})\.png/);
        if (match) carrier = match[1];
      }
      return {
        visible: row.getBoundingClientRect().height > 0 && !!row.offsetParent,
        aria: link ? link.getAttribute('aria-label') : null,
        carrier,
        innerText: row.innerText,
      };
    }),
  };
}"""


def search_url(origin: str, destination: str, depart: str, return_date: str | None) -> str:
    trip = f"{depart} through {return_date}" if return_date else f"{depart} one way"
    query = f"Flights from {origin} to {destination} on {trip}"
    return f"https://www.google.com/travel/flights?q={quote(query)}&hl=en&gl=US&curr=USD"


async def capture() -> dict:
    captured: dict = {}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for origin, destination, depart, return_date in CASES:
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent=USER_AGENT,
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                page = await context.new_page()
                try:
                    await page.goto(
                        search_url(origin, destination, depart, return_date),
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    await page.wait_for_timeout(SETTLE_MS)
                    data = await page.evaluate(EXTRACT_JS)
                except Exception as exc:  # noqa: BLE001 - a capture script, report and continue
                    print(f"{origin}->{destination}: capture failed: {exc}", file=sys.stderr)
                    continue
                finally:
                    await context.close()

                key = f"{origin}_{destination}_{'rt' if return_date else 'ow'}"
                captured[key] = data
                visible = sum(1 for row in data["rows"] if row["visible"])
                with_aria = sum(1 for row in data["rows"] if row["aria"])
                print(
                    f"{key}: {len(data['rows'])} rows, {visible} visible, {with_aria} with aria-label",
                    file=sys.stderr,
                )
        finally:
            await browser.close()
    return captured


def main() -> int:
    captured = asyncio.run(capture())
    if not captured:
        print("nothing captured - refusing to overwrite the existing fixture", file=sys.stderr)
        return 1
    FIXTURE_PATH.write_text(
        json.dumps(captured, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {FIXTURE_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

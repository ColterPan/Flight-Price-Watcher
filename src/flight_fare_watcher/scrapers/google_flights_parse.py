"""Pure parsing of one Google Flights result row - no Playwright, no network.

Google Flights renders each result row's full itinerary into the `aria-label`
of the row's `div[role="link"]`, as one English sentence:

    From 409 US dollars round trip total. Nonstop flight with American.
    Leaves John F. Kennedy International Airport at 6:00 AM on Friday,
    November 20 and arrives at Los Angeles International Airport at 9:22 AM on
    Friday, November 20. Total duration 6 hr 22 min.   1 carry-on bag
    included. 0 checked bags included.  Select flight

That label is the parser's input, deliberately in preference to the row's
`innerText`. Reasons, both found by live recon (see docs/recon_notes.md):

1. It is *complete*. innerText gives price and airline but splitting it into
   departure/arrival/duration/stops depends on positional guessing that breaks
   between nonstop and multi-stop rows.
2. It is *stable*. It is the accessibility label for a screen reader, so it
   changes far less often than Google's minified class names and DOM nesting.

Everything here is a plain function over strings, so it can be unit tested
against captured fixtures with no browser - see
`scripts/capture_google_flights_fixture.py` to re-capture them.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flight_fare_watcher.models.fare import Layover

#: Currency words Google uses in the aria-label, mapped to ISO 4217. The
#: adapter pins curr=USD in the search URL, so USD is the expected case; the
#: rest are a safety net for a locale we did not pin correctly.
_CURRENCY_WORDS: dict[str, str] = {
    "us dollars": "USD",
    "canadian dollars": "CAD",
    "australian dollars": "AUD",
    "singapore dollars": "SGD",
    "euros": "EUR",
    "british pounds": "GBP",
    "japanese yen": "JPY",
    "indian rupees": "INR",
    "swiss francs": "CHF",
}

_PRICE_RE = re.compile(
    r"From\s+(?P<amount>[\d,]+(?:\.\d+)?)\s+(?P<currency>[A-Za-z][A-Za-z ]*?)"
    r"(?:\s+(?P<trip>round trip|one way)\s+total)?\s*\."
)
_STOPS_RE = re.compile(
    r"(?:(?P<nonstop>Nonstop)|(?P<count>\d+)\s+stops?)\s+flight"
    r"(?:\s+with\s+(?P<airlines>[^.]+?))?\."
)
_OPERATED_RE = re.compile(r"Operated by\s+(?P<operator>[^.]+?)\.")
_LEG_RE = re.compile(
    r"Leaves\s+(?P<dep_airport>.+?)\s+at\s+(?P<dep_time>\d{1,2}:\d{2}\s?[AP]M)"
    r"(?:\s+on\s+(?P<dep_day>[A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2}))?"
    r"\s+and\s+arrives\s+at\s+(?P<arr_airport>.+?)\s+at\s+(?P<arr_time>\d{1,2}:\d{2}\s?[AP]M)"
    r"(?:\s+on\s+(?P<arr_day>[A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2}))?\s*\."
)
_DURATION_RE = re.compile(
    r"Total duration\s+(?P<duration>\d+\s*hr(?:\s*\d+\s*min)?|\d+\s*min)\s*\."
)
_LAYOVER_RE = re.compile(
    r"Layover\s+\(\d+\s+of\s+\d+\)\s+is\s+an?\s+"
    r"(?P<duration>\d+\s*hr(?:\s*\d+\s*min)?|\d+\s*min)"
    r"\s+layover\s+at\s+(?P<airport>[^.]+?)(?:\s+in\s+(?P<city>[^.]+?))?\s*\."
)
_CARRY_ON_RE = re.compile(r"(?P<count>\d+)\s+carry-on bags?\s+included")
_CHECKED_RE = re.compile(r"(?P<count>\d+)\s+checked bags?\s+included")
_HR_MIN_RE = re.compile(r"(?:(?P<hours>\d+)\s*hr)?(?:\s*(?P<minutes>\d+)\s*min)?")
_DAY_RE = re.compile(r"[A-Za-z]+,\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})")

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

#: How far past the searched departure date an arrival may legitimately fall.
#: Long-haul with long layovers can arrive 2-3 days later; anything beyond
#: this means we mis-parsed the day, so we decline to guess a date at all.
_MAX_ARRIVAL_LAG_DAYS = 5


def parse_hr_min(text: str | None) -> int | None:
    """Convert "6 hr 22 min" / "2 hr" / "45 min" to total minutes."""
    if not text:
        return None
    match = _HR_MIN_RE.fullmatch(text.strip())
    if match is None:
        return None
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    total = hours * 60 + minutes
    return total or None


def _normalize_time(text: str) -> str:
    """Collapse inner whitespace in a clock time and upper-case the meridiem."""
    return re.sub(r"\s+", " ", text).strip().upper()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def resolve_day(day_text: str | None, reference: date) -> date | None:
    """Resolve "Friday, November 20" to a real date near `reference`.

    Google omits the year. We pick the occurrence of that month/day closest to
    the searched departure date, which also handles a search spanning a New
    Year boundary (depart Dec 30, arrive Jan 1).
    """
    if not day_text:
        return None
    match = _DAY_RE.search(day_text)
    if match is None:
        return None
    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    day = int(match.group("day"))

    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue  # e.g. Feb 29 in a non-leap year
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: abs((candidate - reference).days))


def _combine(day: date | None, time_text: str | None) -> datetime | None:
    if day is None or not time_text:
        return None
    try:
        parsed = datetime.strptime(_normalize_time(time_text), "%I:%M %p")
    except ValueError:
        return None
    return datetime.combine(day, parsed.time())


def _parse_price(aria_label: str) -> tuple[Decimal, str, str | None] | None:
    match = _PRICE_RE.search(aria_label)
    if match is None:
        return None
    try:
        price = Decimal(match.group("amount").replace(",", ""))
    except InvalidOperation:
        return None
    if price <= 0:
        return None

    currency = _CURRENCY_WORDS.get(_squash(match.group("currency")).lower(), "USD")

    trip_word = match.group("trip")
    trip_type = None
    if trip_word == "round trip":
        trip_type = "round_trip"
    elif trip_word == "one way":
        trip_type = "one_way"
    return price, currency, trip_type


def _parse_leg(aria_label: str, depart_date: date, duration_minutes: int | None) -> dict:
    """Departure/arrival airports, clock times and resolved datetimes."""
    match = _LEG_RE.search(aria_label)
    if match is None:
        return {}

    depart_time = _normalize_time(match.group("dep_time"))
    arrive_time = _normalize_time(match.group("arr_time"))

    depart_day = resolve_day(match.group("dep_day"), depart_date) or depart_date
    depart_at = _combine(depart_day, depart_time)

    arrive_at = _combine(resolve_day(match.group("arr_day"), depart_date), arrive_time)
    if arrive_at is None and depart_at is not None and duration_minutes:
        # No explicit arrival day in the label: derive it from the duration.
        arrive_at = depart_at + timedelta(minutes=duration_minutes)
    if arrive_at is not None and depart_at is not None:
        lag = (arrive_at.date() - depart_at.date()).days
        if lag < 0 or lag > _MAX_ARRIVAL_LAG_DAYS:
            arrive_at = None  # mis-parsed; better absent than wrong

    return {
        "origin_airport_name": _squash(match.group("dep_airport")),
        "destination_airport_name": _squash(match.group("arr_airport")),
        "depart_time": depart_time,
        "arrive_time": arrive_time,
        "depart_at": depart_at,
        "arrive_at": arrive_at,
    }


def _parse_layovers(aria_label: str) -> list[Layover]:
    layovers = []
    for match in _LAYOVER_RE.finditer(aria_label):
        city = match.group("city")
        layovers.append(
            Layover(
                airport=_squash(match.group("airport")),
                city=_squash(city) if city else None,
                duration_minutes=parse_hr_min(match.group("duration")),
            )
        )
    return layovers


def parse_aria_label(aria_label: str, depart_date: date) -> dict | None:
    """Parse one row's aria-label into itinerary fields.

    Returns `None` when the label has no price or no flight description - that
    is how promo/advert rows get skipped without treating the whole scrape as
    broken. `depart_date` is the date that was searched for, used to recover
    the year Google omits from its day names.
    """
    if not aria_label:
        return None

    priced = _parse_price(aria_label)
    stops_match = _STOPS_RE.search(aria_label)
    if priced is None or stops_match is None:
        return None
    price, currency, trip_type = priced

    duration_match = _DURATION_RE.search(aria_label)
    duration_minutes = parse_hr_min(duration_match.group("duration")) if duration_match else None

    operated_match = _OPERATED_RE.search(aria_label)
    carry_on_match = _CARRY_ON_RE.search(aria_label)
    checked_match = _CHECKED_RE.search(aria_label)
    airlines = stops_match.group("airlines")

    parsed: dict = {
        "price": price,
        "currency": currency,
        "trip_type": trip_type,
        "stops": 0 if stops_match.group("nonstop") else int(stops_match.group("count")),
        "airline": _squash(airlines) if airlines else None,
        "operated_by": _squash(operated_match.group("operator")) if operated_match else None,
        "duration_minutes": duration_minutes,
        "layovers": _parse_layovers(aria_label),
        "carry_on_bags_included": int(carry_on_match.group("count")) if carry_on_match else None,
        "checked_bags_included": int(checked_match.group("count")) if checked_match else None,
        "origin_airport_name": None,
        "destination_airport_name": None,
        "depart_time": None,
        "arrive_time": None,
        "depart_at": None,
        "arrive_at": None,
    }
    parsed.update(_parse_leg(aria_label, depart_date, duration_minutes))
    return parsed

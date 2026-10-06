import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.google_flights import build_search_url, dedupe_fares
from flight_fare_watcher.scrapers.google_flights_parse import parse_aria_label, parse_hr_min, resolve_day
from flight_fare_watcher.models.fare import FareResult

from ..conftest import future_date

# Captured live from real Google Flights pages - see
# scripts/capture_google_flights_fixture.py to re-capture.
FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "sample_html" / "google_flights_rows_v2.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _query(**overrides) -> SearchQuery:
    defaults = dict(origin="JFK", destination="LAX", depart_date=future_date())
    defaults.update(overrides)
    return SearchQuery(**defaults)


def test_build_search_url_one_way():
    url = build_search_url(_query(return_date=None))
    assert url.startswith("https://www.google.com/travel/flights?q=")
    assert "JFK" in url and "LAX" in url and "one%20way" in url


def test_build_search_url_round_trip_has_no_one_way_marker():
    return_date = future_date(64)
    url = build_search_url(_query(return_date=return_date))
    assert "one%20way" not in url
    assert return_date.isoformat() in url


def test_build_search_url_applies_passenger_count():
    url = build_search_url(_query(adults=3))
    assert "3%20adults" in url


def test_build_search_url_applies_cabin():
    url = build_search_url(_query(cabin="business"))
    assert "business%20class" in url


def test_build_search_url_nonstop_only():
    url = build_search_url(_query(max_stops=0))
    assert "nonstop" in url


# --- aria-label parsing, against real captured rows ---


def test_parse_aria_label_nonstop_round_trip_row():
    fixture = _load_fixture()
    rows = [row for row in fixture["JFK_LAX_rt"]["rows"] if row["visible"]]
    parsed = parse_aria_label(rows[0]["aria"], date(2026, 11, 20))

    assert parsed is not None
    assert parsed["price"] == Decimal("409")
    assert parsed["currency"] == "USD"
    assert parsed["trip_type"] == "round_trip"
    assert parsed["stops"] == 0
    assert parsed["airline"] == "American"
    assert parsed["depart_time"] == "6:00 AM"
    assert parsed["arrive_time"] == "9:22 AM"
    assert parsed["duration_minutes"] == 382
    assert parsed["carry_on_bags_included"] == 1
    assert parsed["checked_bags_included"] == 0
    assert parsed["layovers"] == []


def test_parse_aria_label_all_visible_rows_are_parseable_for_both_fixtures():
    fixture = _load_fixture()
    for key, depart in (("JFK_LAX_rt", date(2026, 11, 20)), ("BOS_SIN_ow", date(2026, 12, 15))):
        rows = [row for row in fixture[key]["rows"] if row["visible"]]
        assert rows, f"fixture {key} has no visible rows - re-capture it"
        for row in rows:
            parsed = parse_aria_label(row["aria"], depart)
            assert parsed is not None, f"{key}: failed to parse {row['aria']!r}"
            assert parsed["price"] > 0


def test_parse_aria_label_multistop_longhaul_row_has_layover_and_crosses_days():
    fixture = _load_fixture()
    rows = [row for row in fixture["BOS_SIN_ow"]["rows"] if row["visible"]]
    turkish = next(row for row in rows if row["carrier"] == "TK")
    parsed = parse_aria_label(turkish["aria"], date(2026, 12, 15))

    assert parsed is not None
    assert parsed["stops"] == 1
    assert parsed["airline"] == "Turkish Airlines"
    assert len(parsed["layovers"]) == 1
    assert parsed["layovers"][0].city == "Istanbul"
    assert parsed["depart_at"].date() == date(2026, 12, 15)
    assert parsed["arrive_at"].date() == date(2026, 12, 17)  # crosses two midnights


def test_parse_aria_label_operated_by_is_captured():
    fixture = _load_fixture()
    rows = [row for row in fixture["BOS_SIN_ow"]["rows"] if row["visible"]]
    operated = next(row for row in rows if "Operated by" in (row["aria"] or ""))
    parsed = parse_aria_label(operated["aria"], date(2026, 12, 15))
    assert parsed["operated_by"]


def test_parse_aria_label_returns_none_for_empty_or_missing_label():
    assert parse_aria_label("", date(2026, 9, 1)) is None
    assert parse_aria_label(None, date(2026, 9, 1)) is None  # type: ignore[arg-type]


def test_parse_aria_label_returns_none_for_label_without_price():
    assert parse_aria_label("Track prices for this route.", date(2026, 9, 1)) is None


def test_parse_aria_label_handles_thousands_separator_in_price():
    label = (
        "From 1,249 US dollars round trip total. Nonstop flight with Delta. "
        "Leaves JFK at 8:30 AM on Friday, September 1 and arrives at LAX at "
        "11:28 AM on Friday, September 1. Total duration 5 hr 58 min."
    )
    parsed = parse_aria_label(label, date(2026, 9, 1))
    assert parsed is not None
    assert parsed["price"] == Decimal("1249")


# --- helper functions ---


@pytest.mark.parametrize(
    "text,expected",
    [
        ("6 hr 22 min", 382),
        ("2 hr", 120),
        ("45 min", 45),
        (None, None),
        ("", None),
        ("garbage", None),
    ],
)
def test_parse_hr_min(text, expected):
    assert parse_hr_min(text) == expected


def test_resolve_day_picks_closest_occurrence_near_year_boundary():
    # Departing Dec 30, arriving "Thursday, January 1" should resolve to the
    # January immediately after, not a year away in either direction.
    reference = date(2026, 12, 30)
    resolved = resolve_day("Thursday, January 1", reference)
    assert resolved == date(2027, 1, 1)


def test_resolve_day_returns_none_for_unparseable_text():
    assert resolve_day("not a day", date(2026, 1, 1)) is None
    assert resolve_day(None, date(2026, 1, 1)) is None


# --- dedupe ---


def _fare(**overrides) -> FareResult:
    from datetime import datetime

    defaults = dict(
        site="google_flights",
        origin="JFK",
        destination="LAX",
        depart_date=date(2026, 9, 1),
        return_date=None,
        price=Decimal("300"),
        currency="USD",
        deep_link="https://example.com",
        scraped_at=datetime(2026, 7, 28, 12, 0, 0),
        airline="Test Air",
        depart_time="6:00 AM",
        arrive_time="9:00 AM",
        duration_minutes=180,
        stops=0,
    )
    defaults.update(overrides)
    return FareResult(**defaults)


def test_dedupe_fares_drops_exact_repeats_keeping_first_occurrence():
    first = _fare(carrier_code="AA")
    repeat = _fare(carrier_code="AA")
    different = _fare(carrier_code="B6", depart_time="7:00 AM")

    result = dedupe_fares([first, repeat, different])
    assert result == [first, different]


def test_dedupe_fares_keeps_same_itinerary_at_a_different_price():
    cheap = _fare(carrier_code="AA", price=Decimal("300"))
    expensive = _fare(carrier_code="AA", price=Decimal("450"))

    result = dedupe_fares([cheap, expensive])
    assert len(result) == 2

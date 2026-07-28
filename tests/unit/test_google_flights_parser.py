import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from flight_fare_watcher.scrapers.google_flights import build_search_url, parse_flight_row

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "sample_html" / "google_flights_rows.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_build_search_url_one_way():
    url = build_search_url("JFK", "LAX", date(2026, 9, 1), None)
    assert url.startswith("https://www.google.com/travel/flights?q=")
    assert "JFK" in url and "LAX" in url and "one%20way" in url


def test_build_search_url_round_trip_has_no_one_way_marker():
    url = build_search_url("JFK", "LAX", date(2026, 9, 1), date(2026, 9, 5))
    assert "one%20way" not in url
    assert "2026-09-05" in url


def test_parse_flight_row_against_real_captured_round_trip_rows():
    fixture = _load_fixture()
    expected_prices = [Decimal("351"), Decimal("367"), Decimal("367")]
    expected_airlines = ["JetBlue", "American", "American"]

    for row_text, expected_price, expected_airline in zip(
        fixture["round_trip_rows"], expected_prices, expected_airlines
    ):
        parsed = parse_flight_row(row_text)
        assert parsed is not None
        assert parsed["price"] == expected_price
        assert parsed["airline"] == expected_airline


def test_parse_flight_row_against_real_captured_one_way_row():
    fixture = _load_fixture()
    parsed = parse_flight_row(fixture["one_way_rows"][0])
    assert parsed is not None
    assert parsed["price"] == Decimal("189")
    assert parsed["airline"] == "JetBlue"


def test_parse_flight_row_returns_none_for_row_without_price():
    # Synthetic: a promo/informational row with no fare, should be skipped not crash.
    row_text = "Track prices\nSep 1 - 5\nAny dates"
    assert parse_flight_row(row_text) is None


def test_parse_flight_row_returns_none_for_row_without_two_times():
    row_text = "Prices are currently typical\nView price history"
    assert parse_flight_row(row_text) is None


def test_parse_flight_row_handles_price_with_thousands_separator():
    # Synthetic: business-class-style fare with a comma in the price.
    row_text = "8:30 AM\n – \n11:28 AM\nDelta\n5 hr 58 min\nJFK–LAX\nNonstop\n$1,249\nround trip"
    parsed = parse_flight_row(row_text)
    assert parsed is not None
    assert parsed["price"] == Decimal("1249")


def test_parse_flight_row_handles_one_stop_layover_line():
    # Synthetic: a 1-stop row has an extra layover-duration line before the
    # stops count that the nonstop rows don't have.
    row_text = (
        "5:50 AM\n – \n1:20 PM\nJetBlue\n10 hr 30 min\nJFK–LAX\n"
        "1 stop\n2 hr 10 min FLL\n549 kg CO2e\n+69% emissions\n1\n0\n$335\nround trip"
    )
    parsed = parse_flight_row(row_text)
    assert parsed is not None
    assert parsed["price"] == Decimal("335")
    assert parsed["airline"] == "JetBlue"

from datetime import datetime
from decimal import Decimal

import pytest

from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.scrapers.amadeus_api import AmadeusAdapter, parse_iso_duration, parse_offer

from ..conftest import future_date


def _query(**overrides) -> SearchQuery:
    defaults = dict(origin="JFK", destination="LAX", depart_date=future_date())
    defaults.update(overrides)
    return SearchQuery(**defaults)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PT6H22M", 382),
        ("PT2H", 120),
        ("PT45M", 45),
        ("P1DT2H", 1560),
        (None, None),
        ("", None),
        ("not-a-duration", None),
    ],
)
def test_parse_iso_duration(value, expected):
    assert parse_iso_duration(value) == expected


def _nonstop_offer(price="409.00", currency="USD") -> dict:
    return {
        "price": {"grandTotal": price, "currency": currency},
        "itineraries": [
            {
                "duration": "PT6H22M",
                "segments": [
                    {
                        "carrierCode": "AA",
                        "departure": {"iataCode": "JFK", "at": "2026-11-20T06:00:00"},
                        "arrival": {"iataCode": "LAX", "at": "2026-11-20T09:22:00"},
                    }
                ],
            }
        ],
    }


def _one_stop_offer() -> dict:
    return {
        "price": {"grandTotal": "1424.00", "currency": "USD"},
        "itineraries": [
            {
                "duration": "PT23H45M",
                "segments": [
                    {
                        "carrierCode": "TK",
                        "departure": {"iataCode": "BOS", "at": "2026-12-15T20:00:00"},
                        "arrival": {"iataCode": "IST", "at": "2026-12-16T13:20:00"},
                    },
                    {
                        "carrierCode": "TK",
                        "departure": {"iataCode": "IST", "at": "2026-12-16T17:15:00"},
                        "arrival": {"iataCode": "SIN", "at": "2026-12-17T08:45:00"},
                    },
                ],
            }
        ],
    }


def test_parse_offer_nonstop_one_way():
    scraped_at = datetime.now()
    fare = parse_offer(_nonstop_offer(), {"AA": "AMERICAN AIRLINES"}, _query(), "https://example.com", scraped_at)

    assert fare is not None
    assert fare.price == Decimal("409")
    assert fare.currency == "USD"
    assert fare.carrier_code == "AA"
    assert fare.airline == "American Airlines"
    assert fare.trip_type == "one_way"
    assert fare.stops == 0
    assert fare.duration_minutes == 382
    assert fare.depart_time == "6:00 AM"
    assert fare.arrive_time == "9:22 AM"


def test_parse_offer_one_stop_round_trip_counts_stops_and_layover():
    query = _query(origin="BOS", destination="SIN", depart_date=future_date(30), return_date=future_date(40))
    offer = _one_stop_offer()
    # Simulate a round trip by duplicating the itinerary - what matters for
    # trip_type is len(itineraries) > 1, not its content.
    offer["itineraries"].append(offer["itineraries"][0])

    fare = parse_offer(offer, {"TK": "TURKISH AIRLINES"}, query, "https://example.com", datetime.now())

    assert fare is not None
    assert fare.trip_type == "round_trip"
    assert fare.stops == 1
    assert len(fare.layovers) == 1
    assert fare.layovers[0].airport == "IST"
    assert fare.layovers[0].duration_minutes == 235  # 13:20 -> 17:15


def test_parse_offer_returns_none_for_malformed_offer():
    assert parse_offer({}, {}, _query(), "https://example.com", datetime.now()) is None
    assert parse_offer({"price": {}}, {}, _query(), "https://example.com", datetime.now()) is None


def test_parse_offer_returns_none_for_non_positive_price():
    offer = _nonstop_offer(price="0")
    assert parse_offer(offer, {}, _query(), "https://example.com", datetime.now()) is None


def test_parse_offer_returns_none_for_unparseable_price():
    offer = _nonstop_offer(price="not-a-number")
    assert parse_offer(offer, {}, _query(), "https://example.com", datetime.now()) is None


# --- adapter-level behavior ---


@pytest.mark.asyncio
async def test_amadeus_adapter_reports_not_configured_without_credentials():
    adapter = AmadeusAdapter(api_key="", api_secret="")
    outcome = await adapter.search(_query(), context=None)
    assert outcome.status == "not_configured"
    assert "AMADEUS_API_KEY" in outcome.diagnostic


def test_amadeus_adapter_is_configured_only_with_both_key_and_secret():
    assert AmadeusAdapter(api_key="", api_secret="").is_configured is False
    assert AmadeusAdapter(api_key="k", api_secret="").is_configured is False
    assert AmadeusAdapter(api_key="k", api_secret="s").is_configured is True


def test_amadeus_adapter_does_not_need_a_browser():
    assert AmadeusAdapter().needs_browser is False


def test_amadeus_adapter_search_params_include_nonstop_flag_only_when_requested():
    adapter = AmadeusAdapter(api_key="k", api_secret="s")
    assert "nonStop" not in adapter._search_params(_query())
    assert adapter._search_params(_query(max_stops=0))["nonStop"] == "true"


def test_amadeus_adapter_search_params_include_return_date_only_for_round_trip():
    adapter = AmadeusAdapter(api_key="k", api_secret="s")
    one_way_params = adapter._search_params(_query())
    round_trip_params = adapter._search_params(_query(depart_date=future_date(30), return_date=future_date(40)))
    assert "returnDate" not in one_way_params
    assert "returnDate" in round_trip_params

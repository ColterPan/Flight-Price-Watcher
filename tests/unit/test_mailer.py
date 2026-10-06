from datetime import datetime
from decimal import Decimal

from flight_fare_watcher.alerts.mailer import build_alert_body, describe_fare, format_duration
from flight_fare_watcher.models.fare import FareResult, Layover
from flight_fare_watcher.models.watch import WatchedRouteCreate

from ..conftest import future_date


def _fare(**overrides) -> FareResult:
    defaults = dict(
        site="google_flights",
        origin="JFK",
        destination="LAX",
        depart_date=future_date(),
        price=Decimal("189"),
        currency="USD",
        deep_link="https://example.com/search",
        scraped_at=datetime.now(),
        airline="JetBlue",
        depart_time="6:00 AM",
        arrive_time="9:22 AM",
        duration_minutes=382,
        stops=0,
    )
    defaults.update(overrides)
    return FareResult(**defaults)


def _watch(**overrides):
    defaults = dict(origin="JFK", destination="LAX", depart_date=future_date())
    defaults.update(overrides)
    created = WatchedRouteCreate(**defaults)
    # build_alert_body takes a WatchedRoute (has id/created_at); fake the
    # extra fields rather than pulling in the repository for a pure test.
    from flight_fare_watcher.models.watch import WatchedRoute

    return WatchedRoute(id=1, created_at=datetime.now(), **created.model_dump())


def test_format_duration_hours_and_minutes():
    assert format_duration(382) == "6h 22m"


def test_format_duration_zero_or_none_is_a_dash():
    assert format_duration(0) == "-"
    assert format_duration(None) == "-"


def test_describe_fare_includes_price_airline_times_and_stops():
    description = describe_fare(_fare())
    assert "$189 USD" in description
    assert "JetBlue" in description
    assert "6:00 AM - 9:22 AM" in description
    assert "nonstop" in description


def test_describe_fare_shows_stop_count_when_not_nonstop():
    description = describe_fare(_fare(stops=1))
    assert "1 stop(s)" in description


def test_build_alert_body_includes_route_dates_and_price():
    body = build_alert_body(_watch(target_price=Decimal("200")), _fare(), previous_min=Decimal("250"))
    assert "JFK -> LAX" in body
    assert "$189 USD" in body
    assert "down $61" in body
    assert "Your target: $200" in body


def test_build_alert_body_omits_previous_price_line_when_none_known():
    body = build_alert_body(_watch(), _fare(), previous_min=None)
    assert "Previous:" not in body


def test_build_alert_body_includes_layover_detail():
    fare = _fare(stops=1, layovers=[Layover(airport="IST", city="Istanbul", duration_minutes=235)])
    body = build_alert_body(_watch(), fare, previous_min=None)
    assert "Layover: 3h 55m in Istanbul" in body


def test_build_alert_body_prefers_booking_url_when_present():
    fare = _fare(booking_url="https://www.google.com/travel/flights/booking?tfs=abc")
    body = build_alert_body(_watch(), fare, previous_min=None)
    assert "Book this flight: https://www.google.com/travel/flights/booking?tfs=abc" in body
    assert "All results:" in body


def test_build_alert_body_falls_back_to_deep_link_without_booking_url():
    body = build_alert_body(_watch(), _fare(booking_url=None), previous_min=None)
    assert "Book here:" in body

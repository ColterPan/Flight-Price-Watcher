from decimal import Decimal

from flight_fare_watcher.alerts.threshold import is_new_low, meets_alert_criteria


def test_is_new_low_true_when_no_history_exists():
    assert is_new_low(Decimal("200"), None) is True


def test_is_new_low_true_when_candidate_below_historical_min():
    assert is_new_low(Decimal("150"), Decimal("200")) is True


def test_is_new_low_false_when_candidate_equals_historical_min():
    assert is_new_low(Decimal("200"), Decimal("200")) is False


def test_is_new_low_false_when_candidate_above_historical_min():
    assert is_new_low(Decimal("250"), Decimal("200")) is False


def test_meets_alert_criteria_true_for_first_ever_observation_with_no_target():
    assert meets_alert_criteria(Decimal("300"), None, None) is True


def test_meets_alert_criteria_false_when_not_a_new_low():
    assert meets_alert_criteria(Decimal("250"), None, Decimal("200")) is False


def test_meets_alert_criteria_true_when_new_low_and_no_target_set():
    assert meets_alert_criteria(Decimal("150"), None, Decimal("200")) is True


def test_meets_alert_criteria_false_when_new_low_but_above_target():
    assert meets_alert_criteria(Decimal("180"), Decimal("150"), Decimal("200")) is False


def test_meets_alert_criteria_true_when_new_low_and_at_or_below_target():
    assert meets_alert_criteria(Decimal("150"), Decimal("150"), Decimal("200")) is True


def test_meets_alert_criteria_false_when_target_set_but_not_a_new_low_even_if_below_target():
    # candidate is below target but historical min is even lower - not a new low, don't alert.
    assert meets_alert_criteria(Decimal("140"), Decimal("150"), Decimal("100")) is False

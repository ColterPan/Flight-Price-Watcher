"""Pure alert-decision logic - no I/O, so it's trivially unit-testable."""

from __future__ import annotations

from decimal import Decimal


def is_new_low(candidate: Decimal, historical_min: Decimal | None) -> bool:
    if historical_min is None:
        return True
    return candidate < historical_min


def meets_alert_criteria(
    candidate: Decimal,
    target_price: Decimal | None,
    historical_min: Decimal | None,
) -> bool:
    """Alert when `candidate` is a new all-time low AND, if a target is set, at/below it.

    If no target price was set on the watch, any new low triggers an alert.
    This is a deliberate default to avoid alert fatigue: a lower price that
    still isn't a new low, or one above the target, doesn't notify.
    """
    if not is_new_low(candidate, historical_min):
        return False
    if target_price is None:
        return True
    return candidate <= target_price

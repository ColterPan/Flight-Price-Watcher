from decimal import Decimal

import pytest

from flight_fare_watcher.currency import (
    ExchangeRateCache,
    ExchangeRateError,
    ExchangeRateSnapshot,
    convert,
    round_for_display,
)


def _snapshot(base="USD", rates=None, as_of="2026-10-05", fetched_at=0.0, stale=False):
    return ExchangeRateSnapshot(
        base=base,
        rates=rates or {"EUR": Decimal("0.9"), "GBP": Decimal("0.75"), "JPY": Decimal("150")},
        as_of=as_of,
        fetched_at=fetched_at,
        stale=stale,
    )


# --- convert() ---


def test_convert_same_currency_is_identity_no_rounding_drift():
    snapshot = _snapshot()
    assert convert(Decimal("123.45"), "USD", "USD", snapshot) == Decimal("123.45")


def test_convert_base_to_other_currency():
    snapshot = _snapshot()
    result = convert(Decimal("100"), "USD", "EUR", snapshot)
    assert result == Decimal("90")


def test_convert_other_currency_to_base():
    snapshot = _snapshot()
    result = convert(Decimal("90"), "EUR", "USD", snapshot)
    assert result == Decimal("100")


def test_convert_between_two_non_base_currencies_routes_through_base():
    snapshot = _snapshot()
    # 90 EUR -> 100 USD -> 75 GBP
    result = convert(Decimal("90"), "EUR", "GBP", snapshot)
    assert result == Decimal("75")


def test_convert_returns_none_for_unknown_currency():
    snapshot = _snapshot()
    assert convert(Decimal("100"), "USD", "XYZ", snapshot) is None
    assert convert(Decimal("100"), "XYZ", "USD", snapshot) is None


def test_convert_rate_to_base_itself_is_always_one():
    snapshot = _snapshot()
    assert snapshot.rate_to("USD") == Decimal("1")


# --- round_for_display() ---


@pytest.mark.parametrize(
    "amount,currency,expected",
    [
        (Decimal("123.456"), "USD", Decimal("123.46")),
        (Decimal("123.454"), "USD", Decimal("123.45")),
        (Decimal("123.455"), "USD", Decimal("123.46")),  # half rounds up
        (Decimal("12345.6"), "JPY", Decimal("12346")),  # zero-decimal currency
        (Decimal("100"), "EUR", Decimal("100.00")),
    ],
)
def test_round_for_display(amount, currency, expected):
    assert round_for_display(amount, currency) == expected


# --- ExchangeRateCache ---


@pytest.mark.asyncio
async def test_cache_returns_freshly_fetched_rates(monkeypatch):
    import flight_fare_watcher.currency as currency_module

    async def fake_fetch(base):
        return _snapshot(base=base, fetched_at=100.0)

    monkeypatch.setattr(currency_module, "fetch_live_rates", fake_fetch)
    cache = ExchangeRateCache(ttl_seconds=3600)

    snapshot = await cache.get_rates("USD")
    assert snapshot.base == "USD"
    assert snapshot.stale is False


@pytest.mark.asyncio
async def test_cache_reuses_fresh_entry_without_refetching(monkeypatch):
    import flight_fare_watcher.currency as currency_module

    call_count = 0

    async def fake_fetch(base):
        nonlocal call_count
        call_count += 1
        return _snapshot(base=base, fetched_at=currency_module.time.monotonic())

    monkeypatch.setattr(currency_module, "fetch_live_rates", fake_fetch)
    cache = ExchangeRateCache(ttl_seconds=3600)

    await cache.get_rates("USD")
    await cache.get_rates("USD")

    assert call_count == 1


@pytest.mark.asyncio
async def test_cache_refetches_after_ttl_expires(monkeypatch):
    import flight_fare_watcher.currency as currency_module

    call_count = 0
    fake_time = [1000.0]

    async def fake_fetch(base):
        nonlocal call_count
        call_count += 1
        return _snapshot(base=base, fetched_at=fake_time[0])

    monkeypatch.setattr(currency_module, "fetch_live_rates", fake_fetch)
    monkeypatch.setattr(currency_module.time, "monotonic", lambda: fake_time[0])
    cache = ExchangeRateCache(ttl_seconds=60)

    await cache.get_rates("USD")
    fake_time[0] += 120  # past the 60s TTL
    await cache.get_rates("USD")

    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_falls_back_to_stale_copy_when_live_fetch_fails(monkeypatch):
    import flight_fare_watcher.currency as currency_module

    fake_time = [1000.0]
    should_fail = [False]

    async def fake_fetch(base):
        if should_fail[0]:
            raise ExchangeRateError("simulated network failure")
        return _snapshot(base=base, fetched_at=fake_time[0])

    monkeypatch.setattr(currency_module, "fetch_live_rates", fake_fetch)
    monkeypatch.setattr(currency_module.time, "monotonic", lambda: fake_time[0])
    cache = ExchangeRateCache(ttl_seconds=60)

    first = await cache.get_rates("USD")
    assert first.stale is False

    fake_time[0] += 120  # expire the TTL
    should_fail[0] = True
    second = await cache.get_rates("USD")

    assert second.stale is True
    assert second.rates == first.rates  # the actual numbers are still usable


@pytest.mark.asyncio
async def test_cache_raises_when_nothing_cached_and_live_fetch_fails(monkeypatch):
    import flight_fare_watcher.currency as currency_module

    async def failing_fetch(base):
        raise ExchangeRateError("simulated network failure")

    monkeypatch.setattr(currency_module, "fetch_live_rates", failing_fetch)
    cache = ExchangeRateCache(ttl_seconds=3600)

    with pytest.raises(ExchangeRateError):
        await cache.get_rates("USD")


@pytest.mark.asyncio
async def test_cache_does_not_serve_a_too_old_stale_copy(monkeypatch):
    import flight_fare_watcher.currency as currency_module

    fake_time = [0.0]

    async def fake_fetch(base):
        return _snapshot(base=base, fetched_at=fake_time[0])

    monkeypatch.setattr(currency_module, "fetch_live_rates", fake_fetch)
    monkeypatch.setattr(currency_module.time, "monotonic", lambda: fake_time[0])
    cache = ExchangeRateCache(ttl_seconds=60)
    await cache.get_rates("USD")

    # Jump forward well past MAX_STALE_AGE_SECONDS and start failing.
    fake_time[0] += currency_module.MAX_STALE_AGE_SECONDS + 3600

    async def failing_fetch(base):
        raise ExchangeRateError("simulated network failure")

    monkeypatch.setattr(currency_module, "fetch_live_rates", failing_fetch)

    with pytest.raises(ExchangeRateError):
        await cache.get_rates("USD")

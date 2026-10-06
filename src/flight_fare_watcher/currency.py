"""Live currency conversion for displaying fares in the viewer's currency.

Every fare provider in this app prices in USD (Google Flights is pinned via
`curr=USD` in its search URL, Amadeus is asked for `currencyCode=USD`, and the
demo provider always returns USD) - so this module is purely a **display**
layer. The price that is searched, sorted, stored, and compared against a
watch's target/historical-min is always the provider's native amount; a
converted amount is only ever shown alongside it, never substituted into any
of that logic. Converting a target price for comparison would make "a new
low" a function of a currency market moving, not the airfare - that is a
correctness bug waiting to happen, so this module is deliberately kept out of
`alerts/threshold.py` and `db/repository.py` entirely.

Rates come from the Frankfurter API (https://frankfurter.dev): free, no API
key, backed by European Central Bank reference rates, updated on ECB's
schedule (~once per weekday). That update cadence is why a hour-scale cache
is correct here, not a limitation to work around.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import httpx

from flight_fare_watcher.logging_config import get_logger

logger = get_logger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
REQUEST_TIMEOUT_SECONDS = 10.0

#: Currencies offered in the display-currency picker, with their display
#: names. This is every currency Frankfurter/ECB publishes a rate for, plus
#: USD (always present as the implicit base). Keep in sync with the provider
#: adapters' `_CURRENCY_WORDS` tables if either list changes.
SUPPORTED_CURRENCIES: dict[str, str] = {
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "JPY": "Japanese Yen",
    "CAD": "Canadian Dollar",
    "AUD": "Australian Dollar",
    "CHF": "Swiss Franc",
    "CNY": "Chinese Yuan",
    "INR": "Indian Rupee",
    "SGD": "Singapore Dollar",
    "HKD": "Hong Kong Dollar",
    "NZD": "New Zealand Dollar",
    "MXN": "Mexican Peso",
    "BRL": "Brazilian Real",
    "ZAR": "South African Rand",
    "SEK": "Swedish Krona",
    "NOK": "Norwegian Krone",
    "DKK": "Danish Krone",
    "KRW": "South Korean Won",
    "THB": "Thai Baht",
    "PLN": "Polish Zloty",
    "TRY": "Turkish Lira",
    "ILS": "Israeli Shekel",
    "PHP": "Philippine Peso",
    "IDR": "Indonesian Rupiah",
    "MYR": "Malaysian Ringgit",
    "CZK": "Czech Koruna",
    "HUF": "Hungarian Forint",
    "RON": "Romanian Leu",
    "ISK": "Icelandic Krona",
}

#: Currencies conventionally displayed with no decimal places (their
#: smallest common unit isn't 1/100). Every other supported currency is
#: rounded to 2 decimal places for display.
ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset({"JPY", "KRW", "HUF", "ISK"})

#: Cache entries older than this are not served even as a stale fallback -
#: FX-rate data this old is misleading rather than merely approximate.
MAX_STALE_AGE_SECONDS = 24 * 3600 * 7  # 1 week


class ExchangeRateError(Exception):
    """Live rates could not be fetched and no usable cached copy exists."""


@dataclass(frozen=True)
class ExchangeRateSnapshot:
    """Rates for converting 1 unit of `base` into each other currency."""

    base: str
    rates: dict[str, Decimal]
    #: The date these rates are *as of*, per the rate source (not the time we
    #: fetched them - Frankfurter can serve "yesterday's close" for a while
    #: each day before publishing the new one).
    as_of: str
    fetched_at: float  # time.monotonic(), for cache aging only
    stale: bool = False

    def rate_to(self, currency: str) -> Decimal | None:
        if currency == self.base:
            return Decimal("1")
        return self.rates.get(currency)


def convert(amount: Decimal, from_currency: str, to_currency: str, snapshot: ExchangeRateSnapshot) -> Decimal | None:
    """Convert `amount` from `from_currency` to `to_currency` using `snapshot`.

    Returns `None` (never raises, never guesses) if either currency isn't in
    the snapshot - the caller is expected to fall back to showing the native
    amount rather than display a silently-wrong number.
    """
    if from_currency == to_currency:
        return amount

    from_rate = snapshot.rate_to(from_currency)
    to_rate = snapshot.rate_to(to_currency)
    if from_rate is None or to_rate is None or from_rate == 0:
        return None

    amount_in_base = amount / from_rate
    return amount_in_base * to_rate


def round_for_display(amount: Decimal, currency: str) -> Decimal:
    """Round a converted amount the way that currency is conventionally shown."""
    places = Decimal("1") if currency in ZERO_DECIMAL_CURRENCIES else Decimal("0.01")
    return amount.quantize(places, rounding=ROUND_HALF_UP)


async def fetch_live_rates(base: str) -> ExchangeRateSnapshot:
    """Fetch current rates for `base` from Frankfurter. Never returns stale data."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(FRANKFURTER_URL, params={"base": base})
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise ExchangeRateError(f"could not reach the exchange rate service: {exc}") from exc

    try:
        rates = {code: Decimal(str(value)) for code, value in payload["rates"].items()}
        as_of = payload["date"]
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise ExchangeRateError(f"unexpected response from the exchange rate service: {exc}") from exc

    return ExchangeRateSnapshot(base=base, rates=rates, as_of=as_of, fetched_at=time.monotonic())


class ExchangeRateCache:
    """Caches rate snapshots per base currency and serves a stale copy on failure.

    FX rates are the one piece of data in this app where "approximately
    right, always available" beats "exactly right, sometimes missing" - a
    display conversion that briefly uses yesterday's rate is harmless, while
    one that disappears every time the rate API hiccups is just annoying.
    Contrast with `search/cache.py`, which never serves a stale fare - those
    two caches look similar but make opposite tradeoffs on purpose.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, ExchangeRateSnapshot] = {}
        self._lock = asyncio.Lock()

    async def get_rates(self, base: str) -> ExchangeRateSnapshot:
        async with self._lock:
            cached = self._entries.get(base)
            if cached is not None and not cached.stale and time.monotonic() - cached.fetched_at < self._ttl:
                return cached

        try:
            fresh = await fetch_live_rates(base)
        except ExchangeRateError:
            async with self._lock:
                cached = self._entries.get(base)
            if cached is not None and time.monotonic() - cached.fetched_at < MAX_STALE_AGE_SECONDS:
                logger.warning("exchange rates: live fetch failed, serving stale copy for %s", base)
                stale_copy = ExchangeRateSnapshot(
                    base=cached.base,
                    rates=cached.rates,
                    as_of=cached.as_of,
                    fetched_at=cached.fetched_at,
                    stale=True,
                )
                async with self._lock:
                    self._entries[base] = stale_copy
                return stale_copy
            raise

        async with self._lock:
            self._entries[base] = fresh
        return fresh

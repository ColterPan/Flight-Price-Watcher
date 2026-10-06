"""Live currency conversion endpoint.

Fares are always priced in USD by every provider (see currency.py's module
docstring); this endpoint exists purely so the UI can offer "show prices in
<currency>" and convert already-fetched results client-side, instantly,
without re-running a search.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from flight_fare_watcher.currency import SUPPORTED_CURRENCIES, ExchangeRateCache, ExchangeRateError
from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.web.deps import get_exchange_rate_cache

logger = get_logger(__name__)

router = APIRouter()


@router.get("/api/exchange-rates")
async def exchange_rates(
    base: str = Query(default="USD"),
    cache: ExchangeRateCache = Depends(get_exchange_rate_cache),
) -> dict:
    base = base.strip().upper()
    if base not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail=f"unsupported currency code: {base!r}")

    try:
        snapshot = await cache.get_rates(base)
    except ExchangeRateError as exc:
        logger.warning("exchange rates unavailable for %s: %s", base, exc)
        raise HTTPException(
            status_code=503,
            detail="Live exchange rates are temporarily unavailable. Prices are still shown in their original currency.",
        ) from exc

    return {
        "base": snapshot.base,
        "as_of": snapshot.as_of,
        "stale": snapshot.stale,
        "rates": {code: str(rate) for code, rate in snapshot.rates.items()},
        "supported_currencies": SUPPORTED_CURRENCIES,
    }

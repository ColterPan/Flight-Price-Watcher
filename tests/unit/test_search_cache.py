from datetime import datetime
from decimal import Decimal

import pytest

from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.search.cache import SearchCache
from flight_fare_watcher.search.orchestrator import SearchResponse

from ..conftest import future_date


def _query(**overrides) -> SearchQuery:
    defaults = dict(origin="JFK", destination="LAX", depart_date=future_date())
    defaults.update(overrides)
    return SearchQuery(**defaults)


def _response(price="199") -> SearchResponse:
    fare = FareResult(
        site="demo",
        origin="JFK",
        destination="LAX",
        depart_date=future_date(),
        price=Decimal(price),
        currency="USD",
        deep_link="https://example.com",
        scraped_at=datetime.now(),
        airline="Test Air",
    )
    return SearchResponse(
        origin="JFK", destination="LAX", depart_date=future_date(), return_date=None,
        fares=[fare], site_statuses={"demo": "ok"},
    )


@pytest.mark.asyncio
async def test_disabled_cache_never_returns_a_hit():
    cache = SearchCache(ttl_seconds=0)
    await cache.put(_query(), _response())
    assert await cache.get(_query()) is None
    assert cache.enabled is False


@pytest.mark.asyncio
async def test_enabled_cache_returns_a_hit_for_an_identical_query():
    cache = SearchCache(ttl_seconds=300)
    await cache.put(_query(), _response())

    hit = await cache.get(_query())
    assert hit is not None
    assert hit.from_cache is True
    assert hit.fares[0].price == Decimal("199")


@pytest.mark.asyncio
async def test_cache_miss_for_a_different_query():
    cache = SearchCache(ttl_seconds=300)
    await cache.put(_query(), _response())

    assert await cache.get(_query(adults=2)) is None


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(monkeypatch):
    cache = SearchCache(ttl_seconds=1)
    await cache.put(_query(), _response())

    import flight_fare_watcher.search.cache as cache_module

    # Simulate time passing without a real sleep.
    real_monotonic = cache_module.time.monotonic()
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: real_monotonic + 10)

    assert await cache.get(_query()) is None


@pytest.mark.asyncio
async def test_invalidate_removes_only_the_matching_entry():
    cache = SearchCache(ttl_seconds=300)
    await cache.put(_query(), _response())
    await cache.put(_query(adults=2), _response())

    await cache.invalidate(_query())

    assert await cache.get(_query()) is None
    assert await cache.get(_query(adults=2)) is not None


@pytest.mark.asyncio
async def test_clear_removes_everything():
    cache = SearchCache(ttl_seconds=300)
    await cache.put(_query(), _response())
    await cache.clear()
    assert await cache.get(_query()) is None


@pytest.mark.asyncio
async def test_mutating_a_returned_response_does_not_affect_the_cached_copy():
    cache = SearchCache(ttl_seconds=300)
    await cache.put(_query(), _response())

    hit = await cache.get(_query())
    hit.fares[0].booking_url = "https://mutated.example.com"

    second_hit = await cache.get(_query())
    assert second_hit.fares[0].booking_url is None

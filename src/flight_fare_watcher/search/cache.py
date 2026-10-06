"""A tiny in-memory TTL cache for search results.

A live search costs ~19 seconds and a page load on someone else's site. Users
iterate on a search ("same route, show me nonstop only"), and the watch
scheduler may re-check a route the user just searched by hand. Serving an
identical repeat search from memory for a few minutes keeps the UI responsive
and reduces the request load the scrapers put on their sources.

Deliberately in-process and bounded: this is a single-user local tool, so a
dict behind a lock is the right size of solution. Nothing here is persisted -
a restart starts cold, which is correct, because fares go stale.
"""

from __future__ import annotations

import asyncio
import time

from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.search import SearchQuery
from flight_fare_watcher.search.orchestrator import SearchResponse

logger = get_logger(__name__)

#: Upper bound on retained entries, so a long session cannot grow unboundedly.
MAX_ENTRIES = 64


class SearchCache:
    """Maps a `SearchQuery` to its most recent response for `ttl_seconds`."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[tuple, tuple[float, SearchResponse]] = {}
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    async def get(self, query: SearchQuery) -> SearchResponse | None:
        if not self.enabled:
            return None
        async with self._lock:
            entry = self._entries.get(query.cache_key())
            if entry is None:
                return None
            stored_at, response = entry
            if time.monotonic() - stored_at > self._ttl:
                del self._entries[query.cache_key()]
                return None
        logger.info("search cache hit for %s", query.route_label)
        # Copy so a caller mutating fares (e.g. attaching a booking link)
        # cannot alter what the next caller sees.
        return response.model_copy(deep=True, update={"from_cache": True})

    async def put(self, query: SearchQuery, response: SearchResponse) -> None:
        if not self.enabled:
            return
        async with self._lock:
            if len(self._entries) >= MAX_ENTRIES:
                oldest = min(self._entries, key=lambda key: self._entries[key][0])
                del self._entries[oldest]
            self._entries[query.cache_key()] = (
                time.monotonic(),
                response.model_copy(deep=True),
            )

    async def invalidate(self, query: SearchQuery) -> None:
        """Drop any cached response for `query` (used by a forced refresh)."""
        async with self._lock:
            self._entries.pop(query.cache_key(), None)

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

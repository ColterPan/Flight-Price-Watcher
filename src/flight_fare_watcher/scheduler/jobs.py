"""Background watch-check job: re-searches every active watch and alerts on new lows."""

from __future__ import annotations

import sqlite3

from flight_fare_watcher.alerts import mailer, threshold
from flight_fare_watcher.config import Settings
from flight_fare_watcher.db import repository
from flight_fare_watcher.db.database import connect
from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.watch import WatchedRoute
from flight_fare_watcher.scrapers.registry import build_enabled_adapters
from flight_fare_watcher.search.orchestrator import run_search

logger = get_logger(__name__)


async def check_watch(conn: sqlite3.Connection, watch: WatchedRoute, settings: Settings) -> None:
    historical_min_before = repository.get_historical_min(
        conn, watch.origin, watch.destination, watch.depart_date, watch.return_date
    )

    adapters = build_enabled_adapters(
        settings.enabled_site_list,
        scrape_delay_min=settings.scrape_delay_min_seconds,
        scrape_delay_max=settings.scrape_delay_max_seconds,
    )
    response = await run_search(
        adapters,
        watch.origin,
        watch.destination,
        watch.depart_date,
        watch.return_date,
        headless=settings.playwright_headless,
    )

    for site, status in response.site_statuses.items():
        repository.record_scrape_health(conn, site, status, None)

    if response.site_statuses and all(
        status == "blocked_or_structure_changed" for status in response.site_statuses.values()
    ):
        logger.error("watch %s (%s->%s): every enabled adapter is blocked or broken", watch.id, watch.origin, watch.destination)

    if not response.fares:
        return

    # response.fares is sorted ascending by price, so the first entry is cheapest.
    inserted_ids = [repository.insert_fare(conn, fare, watched_route_id=watch.id) for fare in response.fares]
    cheapest = response.fares[0]
    cheapest_fare_id = inserted_ids[0]

    if threshold.meets_alert_criteria(cheapest.price, watch.target_price, historical_min_before):
        to_email = watch.alert_email or settings.alert_to_email
        if not to_email:
            logger.warning("watch %s: alert criteria met but no destination email configured", watch.id)
            return
        mailer.send_price_alert(
            settings,
            to_email,
            subject=f"Price drop: {watch.origin} -> {watch.destination} now ${cheapest.price}",
            body=(
                f"New low fare for {watch.origin} -> {watch.destination} on {watch.depart_date}: "
                f"${cheapest.price} {cheapest.currency} via {cheapest.site} ({cheapest.airline or 'unknown airline'}).\n\n"
                f"Book here: {cheapest.deep_link}"
            ),
        )
        repository.record_alert(conn, watch.id, cheapest_fare_id)


async def run_watch_check_job(database_path: str, settings: Settings) -> None:
    conn = connect(database_path)
    try:
        for watch in repository.list_active_watches(conn):
            try:
                await check_watch(conn, watch, settings)
            except Exception:  # noqa: BLE001 - one broken watch must not stop the others
                logger.exception("watch %s: check failed", watch.id)
    finally:
        conn.close()

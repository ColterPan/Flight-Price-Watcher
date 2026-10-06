"""Background watch-check job: re-searches every active watch and alerts on new lows."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from flight_fare_watcher.alerts import mailer, threshold
from flight_fare_watcher.config import Settings
from flight_fare_watcher.db import repository
from flight_fare_watcher.db.database import connect
from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import HEALTHY_STATUSES
from flight_fare_watcher.models.watch import WatchedRoute
from flight_fare_watcher.scrapers.registry import build_adapters_from_settings
from flight_fare_watcher.search.orchestrator import run_search

logger = get_logger(__name__)


def _summarize_status(site_statuses: dict[str, str]) -> str:
    """One word for the watch list: did this check actually work?"""
    if not site_statuses:
        return "no_providers"
    if any(status == "ok" for status in site_statuses.values()):
        return "ok"
    if all(status not in HEALTHY_STATUSES for status in site_statuses.values()):
        return "all_providers_failing"
    return "no_results"


async def check_watch(
    conn: sqlite3.Connection, watch: WatchedRoute, settings: Settings
) -> Decimal | None:
    """Re-check one watch, persist what it found, and alert if it is a new low.

    Returns the cheapest price found, or `None` if the check produced no fares.
    """
    query = watch.to_query()
    historical_min_before = repository.get_historical_min(
        conn,
        watch.origin,
        watch.destination,
        watch.depart_date,
        watch.return_date,
        adults=watch.adults,
        cabin=watch.cabin,
    )

    response = await run_search(
        build_adapters_from_settings(settings),
        query,
        headless=settings.playwright_headless,
        booking_link_resolve_count=settings.booking_link_resolve_count,
    )

    for site, status in response.site_statuses.items():
        repository.record_scrape_health(
            conn, site, status, response.site_diagnostics.get(site)
        )

    summary = _summarize_status(response.site_statuses)
    if summary == "all_providers_failing":
        logger.error(
            "watch %s (%s): every enabled provider failed - %s",
            watch.id,
            query.route_label,
            response.site_statuses,
        )

    if not response.fares:
        repository.update_watch_check_result(conn, watch.id, summary, None)
        return None

    # response.fares is sorted ascending by price, so the first entry is cheapest.
    inserted_ids = repository.record_search_fares(
        conn, query, response.fares, watched_route_id=watch.id
    )
    cheapest = response.fares[0]
    repository.update_watch_check_result(conn, watch.id, summary, cheapest.price)

    if not threshold.meets_alert_criteria(
        cheapest.price, watch.target_price, historical_min_before
    ):
        return cheapest.price

    to_email = watch.alert_email or settings.alert_to_email
    if not to_email:
        logger.warning(
            "watch %s: alert criteria met but no destination email configured", watch.id
        )
        return cheapest.price

    try:
        mailer.send_price_alert(
            settings,
            to_email,
            subject=f"Price drop: {watch.origin} -> {watch.destination} now ${cheapest.price}",
            body=mailer.build_alert_body(watch, cheapest, historical_min_before),
        )
    except Exception:  # noqa: BLE001 - a bad SMTP config must not look like "no fares found"
        # The search itself succeeded - fares are already persisted and
        # last_status/last_price above already reflect that. Losing the email
        # is a notification failure, not a search failure, so it must not
        # erase the real result (e.g. by the caller then marking this check
        # as "error" with no price).
        logger.exception("watch %s: found a qualifying fare but failed to send the alert email", watch.id)
        return cheapest.price

    # A duplicate-suppressed fare has id -1; only log an alert against a real row.
    if inserted_ids and inserted_ids[0] > 0:
        repository.record_alert(conn, watch.id, inserted_ids[0])
    return cheapest.price


async def run_watch_check_job(database_path: str, settings: Settings) -> None:
    conn = connect(database_path)
    try:
        watches = repository.list_active_watches(conn)
        logger.info("watch check: %s active watch(es)", len(watches))
        for watch in watches:
            try:
                await check_watch(conn, watch, settings)
            except Exception:  # noqa: BLE001 - one broken watch must not stop the others
                logger.exception("watch %s: check failed", watch.id)
                try:
                    repository.update_watch_check_result(conn, watch.id, "error", None)
                except Exception:  # noqa: BLE001 - best effort status write
                    logger.exception("watch %s: could not record failure status", watch.id)
    finally:
        conn.close()

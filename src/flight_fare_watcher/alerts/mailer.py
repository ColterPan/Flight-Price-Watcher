"""smtplib wrapper for price-drop alert emails."""

from __future__ import annotations

import smtplib
from decimal import Decimal
from email.message import EmailMessage

from flight_fare_watcher.config import Settings
from flight_fare_watcher.logging_config import get_logger
from flight_fare_watcher.models.fare import FareResult
from flight_fare_watcher.models.watch import WatchedRoute

logger = get_logger(__name__)

SMTP_TIMEOUT_SECONDS = 15


def format_duration(minutes: int | None) -> str:
    """180 -> "3h 00m". Returns an em dash when the duration is unknown."""
    if not minutes:
        return "-"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def describe_fare(fare: FareResult) -> str:
    """One human-readable line describing an itinerary."""
    parts = [f"${fare.price} {fare.currency}"]
    if fare.airline:
        parts.append(fare.airline)
    if fare.depart_time and fare.arrive_time:
        parts.append(f"{fare.depart_time} - {fare.arrive_time}")
    if fare.duration_minutes:
        parts.append(format_duration(fare.duration_minutes))
    if fare.stops is not None:
        parts.append("nonstop" if fare.stops == 0 else f"{fare.stops} stop(s)")
    return "  |  ".join(parts)


def build_alert_body(
    watch: WatchedRoute,
    fare: FareResult,
    previous_min: Decimal | None,
) -> str:
    """The alert email body: what dropped, by how much, and where to buy it."""
    route = f"{watch.origin} -> {watch.destination}"
    dates = (
        f"{watch.depart_date} to {watch.return_date}"
        if watch.return_date
        else f"{watch.depart_date} (one way)"
    )

    lines = [
        f"New low fare for {route}",
        f"Dates:      {dates}",
        f"Passengers: {watch.adults}",
        f"Cabin:      {watch.cabin.replace('_', ' ')}",
        "",
        f"Now:        ${fare.price} {fare.currency}",
    ]
    if previous_min is not None:
        saving = previous_min - fare.price
        lines.append(f"Previous:   ${previous_min} (down ${saving})")
    if watch.target_price is not None:
        lines.append(f"Your target: ${watch.target_price}")

    lines += ["", "Flight:", f"  {describe_fare(fare)}"]
    if fare.layovers:
        for layover in fare.layovers:
            where = layover.city or layover.airport
            lines.append(f"  Layover: {format_duration(layover.duration_minutes)} in {where}")
    lines += ["", f"Source:     {fare.site}"]

    if fare.booking_url:
        lines += ["", f"Book this flight: {fare.booking_url}"]
        lines.append(f"All results:      {fare.deep_link}")
    else:
        lines += ["", f"Book here: {fare.deep_link}"]

    return "\n".join(lines)


def send_price_alert(settings: Settings, to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.alert_from_email
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)

    logger.info("sent price alert email to %s", to_email)

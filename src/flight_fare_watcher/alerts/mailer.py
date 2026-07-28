"""smtplib wrapper for price-drop alert emails."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from flight_fare_watcher.config import Settings
from flight_fare_watcher.logging_config import get_logger

logger = get_logger(__name__)


def send_price_alert(settings: Settings, to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.alert_from_email
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)

    logger.info("sent price alert email to %s", to_email)

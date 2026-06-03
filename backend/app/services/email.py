"""SMTP email delivery.

A small, single-purpose service: send a text/plain email given the persisted
SMTP settings. Shared — the Phase 8 alerting engine reuses send_email().
"""
import logging
import smtplib
from email.message import EmailMessage

from app.core import crypto
from app.models.other import Settings

logger = logging.getLogger(__name__)


class EmailNotConfigured(Exception):
    """Raised when SMTP host / from-address are not configured."""


def parse_recipients(raw: str | None) -> list[str]:
    return [e.strip() for e in (raw or "").split(",") if e.strip()]


def send_email(s: Settings, subject: str, body: str, recipients: list[str]) -> None:
    if not s.smtp_host or not s.smtp_from_address:
        raise EmailNotConfigured("SMTP is not configured.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.smtp_from_address
    msg["To"] = ", ".join(recipients)
    msg.set_content(body, subtype="plain", charset="utf-8")

    port = s.smtp_port or 587
    password = crypto.decrypt(s.smtp_password_encrypted) if s.smtp_password_encrypted else None

    if s.smtp_encryption == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, port, timeout=15)
    else:
        server = smtplib.SMTP(s.smtp_host, port, timeout=15)
    try:
        if s.smtp_encryption == "tls":
            server.starttls()
        if s.smtp_username and password:
            server.login(s.smtp_username, password)
        server.send_message(msg)
    finally:
        server.quit()


def send_email_safe(s: Settings, subject: str, body: str, recipients: list[str]) -> bool:
    """Best-effort send: swallow EmailNotConfigured and any SMTP/transport error,
    logging a warning. Returns True if the message was handed to SMTP, False
    otherwise. Used by the alerting engine so a missing/broken SMTP config can
    never stop an alert from being recorded or pushed."""
    if not recipients:
        logger.warning("alert email skipped: no recipients configured")
        return False
    try:
        send_email(s, subject, body, recipients)
        return True
    except EmailNotConfigured:
        logger.warning("alert email skipped: SMTP not configured")
        return False
    except Exception:  # noqa: BLE001 — best-effort; never propagate to caller
        logger.warning("alert email send failed", exc_info=True)
        return False

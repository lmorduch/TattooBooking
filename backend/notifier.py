# ABOUTME: Email notification sender using SMTP.
# ABOUTME: Sends alerts for booking hits and scraper breakage.

import logging
import smtplib
from email.mime.text import MIMEText

from config import settings

logger = logging.getLogger(__name__)


def _send(subject: str, body: str) -> None:
    if not settings.smtp_user or not settings.notify_email:
        logger.warning("Email not configured — skipping notification: %s", subject)
        return

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = settings.notify_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, settings.notify_email, msg.as_string())
        logger.info("Sent email: %s", subject)
    except Exception as e:
        logger.error("Failed to send email '%s': %s", subject, e)


def notify_hit(handle: str, hits: list[dict]) -> None:
    lines = [f"@{handle} may have books open!\n"]
    for h in hits:
        lines.append(f"Keyword: {h['keyword']}")
        if h.get("post_url"):
            lines.append(f"Post: {h['post_url']}")
        if h.get("caption_snippet"):
            lines.append(f'Caption: "{h["caption_snippet"]}"')
        lines.append("")
    _send(f"🎨 Books may be open: @{handle}", "\n".join(lines))


def notify_breakage(handle: str, error: str, consecutive: int) -> None:
    body = (
        f"Scraping @{handle} has failed {consecutive} times in a row.\n\n"
        f"Last error:\n{error}\n\n"
        f"Instagram may have changed, or the account requires login. "
        f"Come tell Claude to fix it."
    )
    _send(f"⚠️ Scraper broken: @{handle}", body)


def notify_scheduler_error(error: str) -> None:
    body = (
        f"The daily check scheduler encountered an unexpected error:\n\n{error}\n\n"
        f"Come tell Claude to fix it."
    )
    _send("⚠️ Tattoo tracker scheduler error", body)

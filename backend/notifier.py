# ABOUTME: Email notification sender using Resend's HTTP API.
# ABOUTME: Sends alerts for booking hits and scraper breakage.

import logging

import requests

from config import settings

logger = logging.getLogger(__name__)


def _send(subject: str, body: str) -> None:
    if not settings.resend_api_key or not settings.notify_email:
        logger.warning("Email not configured — skipping notification: %s", subject)
        return

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": "TattooTracker <onboarding@resend.dev>",
                "to": [settings.notify_email],
                "subject": subject,
                "text": body,
            },
            timeout=10,
        )
        resp.raise_for_status()
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


def notify_scan_complete(total_posts: int, hits_by_handle: dict, scanned_to: str | None) -> None:
    hit_count = sum(len(v) for v in hits_by_handle.values())
    if hit_count > 0:
        lines = [f"Scan complete — {total_posts} posts scanned, {hit_count} keyword hit(s).\n"]
        for handle, hits in hits_by_handle.items():
            lines.append(f"@{handle}:")
            for h in hits:
                lines.append(f"  keyword: {h['keyword']}")
                if h.get("post_url"):
                    lines.append(f"  post: {h['post_url']}")
        subject = f"🎨 Scan complete: {hit_count} hit(s) found"
    else:
        lines = [f"Scan complete — {total_posts} posts scanned, no booking keywords found."]
        subject = "✓ Scan complete — nothing found"
    if scanned_to:
        lines.append(f"\nScanned back to: {scanned_to}")
    _send(subject, "\n".join(lines))


def notify_scheduler_error(error: str) -> None:
    body = (
        f"The daily check scheduler encountered an unexpected error:\n\n{error}\n\n"
        f"Come tell Claude to fix it."
    )
    _send("⚠️ Tattoo tracker scheduler error", body)

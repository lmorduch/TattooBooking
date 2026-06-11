# ABOUTME: Instagram scraper using instaloader.
# ABOUTME: Checks recent posts and bio for booking-related keywords.

import logging
import time
from typing import Any

import instaloader

from config import settings

logger = logging.getLogger(__name__)

KEYWORDS = [
    "books open",
    "booking open",
    "now booking",
    "open for booking",
    "taking clients",
    "accepting clients",
    "slots available",
    "dm to book",
    "dm for booking",
    "available for",
    "booking now",
    "taking bookings",
    "flash available",
    "walk-ins welcome",
    "walk ins welcome",
]

# Module-level loader — reuses the session across calls to avoid re-login overhead
_loader: instaloader.Instaloader | None = None


def _get_loader() -> instaloader.Instaloader:
    global _loader
    if _loader is None:
        _loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
        )
        if settings.instagram_username and settings.instagram_password:
            try:
                _loader.login(settings.instagram_username, settings.instagram_password)
                logger.info("Logged into Instagram as %s", settings.instagram_username)
            except Exception as e:
                logger.warning("Instagram login failed: %s", e)
    return _loader


def _find_keywords(text: str) -> str | None:
    if not text:
        return None
    lower = text.lower()
    for kw in KEYWORDS:
        if kw in lower:
            return kw
    return None


def check_artist(handle: str) -> dict[str, Any]:
    """
    Returns:
      {"status": "ok", "hits": []}
      {"status": "hit", "hits": [{"keyword": ..., "post_url": ..., "caption_snippet": ...}]}
      {"status": "error", "error": "...", "breakage": True|False}
    breakage=True means Instagram is blocking us (not a transient network issue).
    """
    L = _get_loader()
    hits = []

    try:
        profile = instaloader.Profile.from_username(L.context, handle)
    except instaloader.exceptions.ProfileNotExistsException:
        return {"status": "error", "error": f"Profile @{handle} does not exist", "breakage": True}
    except instaloader.exceptions.LoginRequiredException:
        return {"status": "error", "error": "Instagram requires login to view this profile", "breakage": True}
    except instaloader.exceptions.ConnectionException as e:
        return {"status": "error", "error": f"Connection error: {e}", "breakage": False}
    except Exception as e:
        return {"status": "error", "error": str(e), "breakage": False}

    # Check bio
    bio_kw = _find_keywords(profile.biography)
    if bio_kw:
        hits.append({
            "keyword": bio_kw,
            "post_url": f"https://www.instagram.com/{handle}/",
            "caption_snippet": profile.biography[:200],
        })

    # Check last 12 posts
    try:
        for i, post in enumerate(profile.get_posts()):
            if i >= 12:
                break
            caption_kw = _find_keywords(post.caption)
            if caption_kw:
                hits.append({
                    "keyword": caption_kw,
                    "post_url": f"https://www.instagram.com/p/{post.shortcode}/",
                    "caption_snippet": (post.caption or "")[:200],
                })
            # Be polite to Instagram's servers
            time.sleep(0.5)
    except instaloader.exceptions.LoginRequiredException:
        return {"status": "error", "error": "Instagram requires login to view posts", "breakage": True}
    except instaloader.exceptions.TooManyRequestsException:
        return {"status": "error", "error": "Rate limited by Instagram", "breakage": True}
    except Exception as e:
        return {"status": "error", "error": str(e), "breakage": False}

    return {"status": "hit" if hits else "ok", "hits": hits}

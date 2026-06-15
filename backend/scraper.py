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

# Module-level loader — reuses the session across calls to avoid re-login overhead.
# Keyed by username so we get a fresh loader if credentials change.
_loader: instaloader.Instaloader | None = None
_loader_username: str | None = None


def _make_loader() -> instaloader.Instaloader:
    return instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )


def _get_loader(session_cookie: str = "") -> instaloader.Instaloader:
    """Returns a loader with session cookie auth if provided, anonymous otherwise."""
    global _loader, _loader_username

    if _loader is None or (_loader_username != session_cookie):
        _loader = _make_loader()
        _loader_username = session_cookie
        if session_cookie:
            _loader.context._session.cookies.update({"sessionid": session_cookie})

    return _loader


def verify_session_cookie(session_cookie: str) -> str | None:
    """Returns the Instagram username if the cookie is valid, else None."""
    try:
        L = _make_loader()
        L.context._session.cookies.update({"sessionid": session_cookie})
        username = L.test_login()
        return username or None
    except Exception:
        return None


def _find_keywords(text: str) -> str | None:
    if not text:
        return None
    lower = text.lower()
    for kw in KEYWORDS:
        if kw in lower:
            return kw
    return None


def check_artist(handle: str, session_cookie: str = "") -> dict[str, Any]:
    """
    Returns:
      {"status": "ok", "hits": []}
      {"status": "hit", "hits": [{"keyword": ..., "post_url": ..., "caption_snippet": ...}]}
      {"status": "error", "error": "...", "breakage": True|False}
    breakage=True means Instagram is blocking us (not a transient network issue).
    """
    L = _get_loader(session_cookie)
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


def import_following(username: str, session_cookie: str) -> list[str]:
    """
    Returns list of handles that the given account follows.
    Raises on auth failure or other errors.
    """
    L = _get_loader(session_cookie)
    profile = instaloader.Profile.from_username(L.context, username)
    handles = []
    for followee in profile.get_followees():
        handles.append(followee.username)
        time.sleep(0.3)
    return handles

# ABOUTME: Instagram scraper using instaloader.
# ABOUTME: Checks recent posts and bio for booking-related keywords.

import logging
import time
from typing import Any

import requests
import instaloader
from requests.adapters import HTTPAdapter

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
_loader_key: tuple[str, str] | None = None  # (session_cookie, user_agent)


class _TimeoutAdapter(HTTPAdapter):
    """Forces a connect+read timeout on every request instaloader makes."""
    def send(self, request, **kwargs):
        kwargs.setdefault("timeout", 30)
        return super().send(request, **kwargs)


def _make_loader(user_agent: str = "") -> instaloader.Instaloader:
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )
    adapter = _TimeoutAdapter()
    L.context._session.mount("https://", adapter)
    L.context._session.mount("http://", adapter)
    if user_agent:
        L.context._session.headers.update({"User-Agent": user_agent})
    return L


def _get_loader(session_cookie: str = "", user_agent: str = "") -> instaloader.Instaloader:
    """Returns a loader with session cookie auth if provided, anonymous otherwise."""
    global _loader, _loader_key

    key = (session_cookie, user_agent)
    if _loader is None or _loader_key != key:
        _loader = _make_loader(user_agent)
        _loader_key = key
        if session_cookie:
            # Prime the session to get csrftoken and other required cookies,
            # then inject our sessionid. Instagram's GraphQL requires csrftoken.
            try:
                _loader.context._session.get("https://www.instagram.com/", timeout=20)
            except Exception:
                pass
            _loader.context._session.cookies.set("sessionid", session_cookie, domain=".instagram.com")

    return _loader


def verify_session_cookie(session_cookie: str, user_agent: str = "") -> str | None:
    """Returns the Instagram username if the cookie is valid, else None."""
    try:
        L = _make_loader(user_agent)
        try:
            L.context._session.get("https://www.instagram.com/", timeout=20)
        except Exception:
            pass
        L.context._session.cookies.set("sessionid", session_cookie, domain=".instagram.com")
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


def check_artist(handle: str, session_cookie: str = "", user_agent: str = "") -> dict[str, Any]:
    """
    Returns:
      {"status": "ok", "hits": []}
      {"status": "hit", "hits": [{"keyword": ..., "post_url": ..., "caption_snippet": ...}]}
      {"status": "error", "error": "...", "breakage": True|False}
    breakage=True means Instagram is blocking us (not a transient network issue).
    Uses the private mobile API — instaloader's GraphQL is broken.
    """
    if not session_cookie:
        return {"status": "error", "error": "Instagram session required", "breakage": True}

    s = _ig_session(session_cookie)
    hits = []

    try:
        resp = s.get(
            "https://i.instagram.com/api/v1/users/web_profile_info/",
            params={"username": handle},
            timeout=30,
        )
        if resp.status_code == 404:
            return {"status": "error", "error": f"Profile @{handle} not found", "breakage": True}
        resp.raise_for_status()
        data = resp.json()
        user = (data.get("data") or {}).get("user") or data.get("user") or {}

        if not user:
            return {"status": "error", "error": f"Profile @{handle} not found", "breakage": True}

        user_id = user.get("id") or user.get("pk")
        bio = user.get("biography") or ""
        bio_kw = _find_keywords(bio)
        if bio_kw:
            hits.append({
                "keyword": bio_kw,
                "post_url": f"https://www.instagram.com/{handle}/",
                "caption_snippet": bio[:200],
            })

        # Check recent posts via feed endpoint
        if user_id:
            feed = s.get(
                f"https://i.instagram.com/api/v1/feed/user/{user_id}/",
                params={"count": 12},
                timeout=30,
            )
            feed.raise_for_status()
            for item in (feed.json().get("items") or [])[:12]:
                cap_obj = item.get("caption") or {}
                caption = cap_obj.get("text") or ""
                kw = _find_keywords(caption)
                if kw:
                    code = item.get("code") or item.get("shortcode") or ""
                    hits.append({
                        "keyword": kw,
                        "post_url": f"https://www.instagram.com/p/{code}/",
                        "caption_snippet": caption[:200],
                    })
                time.sleep(0.3)

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status in (401, 403):
            return {"status": "error", "error": "Instagram session expired or invalid", "breakage": True}
        if status == 429:
            return {"status": "error", "error": "Rate limited by Instagram", "breakage": True}
        return {"status": "error", "error": f"HTTP {status}: {e}", "breakage": False}
    except requests.Timeout:
        return {"status": "error", "error": "Request timed out", "breakage": False}
    except Exception as e:
        return {"status": "error", "error": str(e), "breakage": False}

    return {"status": "hit" if hits else "ok", "hits": hits}


_IG_APP_ID = "936619743392459"
_IG_MOBILE_UA = "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100)"


def _ig_session(session_cookie: str) -> requests.Session:
    """Builds a requests.Session authenticated for Instagram's private API."""
    import requests as _requests
    s = _requests.Session()
    adapter = _TimeoutAdapter()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"X-IG-App-ID": _IG_APP_ID, "User-Agent": _IG_MOBILE_UA})
    # Prime cookies so csrftoken is set, then inject our sessionid
    try:
        s.get("https://www.instagram.com/", timeout=20)
    except Exception:
        pass
    s.cookies.set("sessionid", session_cookie, domain=".instagram.com")
    return s


def _user_id_from_cookie(session_cookie: str) -> str:
    """Extracts the numeric Instagram user ID encoded at the start of the sessionid."""
    return session_cookie.split("%")[0].split(":")[0]


def iter_following(session_cookie: str):
    """
    Yields (username, total) tuples where total is from the first page.
    Uses Instagram's private mobile API, which is not subject to the web GraphQL breakage.
    """
    s = _ig_session(session_cookie)
    user_id = _user_id_from_cookie(session_cookie)

    # Get total count from user info
    info = s.get(f"https://i.instagram.com/api/v1/users/{user_id}/info/", timeout=30)
    info.raise_for_status()
    total = info.json().get("user", {}).get("following_count", 0)

    cursor = None
    while True:
        params: dict = {"count": 200}
        if cursor:
            params["max_id"] = cursor
        resp = s.get(
            f"https://i.instagram.com/api/v1/friendships/{user_id}/following/",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for u in data.get("users", []):
            yield u["username"], total
        cursor = data.get("next_max_id")
        if not cursor:
            break
        time.sleep(0.5)

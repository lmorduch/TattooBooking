# ABOUTME: Instagram scraper using the private mobile API.
# ABOUTME: Checks recent posts and bio for booking-related keywords.

import logging
import random
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

_IG_APP_ID = "936619743392459"
_IG_MOBILE_UA = "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100)"

# Cached session per cookie — priming www.instagram.com once is enough for the whole run.
_ig_session_cache: dict[str, requests.Session] = {}

# Rate limiting: instaloader's research shows ~200 req/11min window.
# We make 2 requests per artist, so we target ~3 req/min = 20s/artist max.
# Base delay between artists (seconds). Jitter is added on top.
_INTER_ARTIST_DELAY = (4.0, 7.0)  # (min, max) uniform random
_INTER_REQUEST_DELAY = (1.0, 2.5)  # between profile fetch and feed fetch within one artist
# On 429: back off this many seconds before retrying (once).
_RATE_LIMIT_BACKOFF = 60


class _TimeoutAdapter(HTTPAdapter):
    """Forces a connect+read timeout on every request."""
    def send(self, request, **kwargs):
        kwargs.setdefault("timeout", 30)
        return super().send(request, **kwargs)


def _build_ig_session(session_cookie: str) -> requests.Session:
    """Creates and primes an authenticated Instagram mobile API session."""
    s = requests.Session()
    adapter = _TimeoutAdapter()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"X-IG-App-ID": _IG_APP_ID, "User-Agent": _IG_MOBILE_UA})
    try:
        s.get("https://www.instagram.com/", timeout=20)
    except Exception:
        pass
    s.cookies.set("sessionid", session_cookie, domain=".instagram.com")
    return s


def get_ig_session(session_cookie: str) -> requests.Session:
    """Returns a cached session for the given cookie, building one if needed."""
    if session_cookie not in _ig_session_cache:
        _ig_session_cache[session_cookie] = _build_ig_session(session_cookie)
    return _ig_session_cache[session_cookie]


def invalidate_ig_session(session_cookie: str) -> None:
    """Drops the cached session so the next call rebuilds it."""
    _ig_session_cache.pop(session_cookie, None)


def _ig_get(s: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET with no automatic retry — 429 propagates immediately for the caller to handle."""
    return s.get(url, **kwargs)


# Module-level loader for verify_session_cookie (still uses instaloader's test_login).
_loader: instaloader.Instaloader | None = None
_loader_key: tuple[str, str] | None = None


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


def _resolve_user_id(s: requests.Session, handle: str) -> tuple[str | None, str]:
    """
    Resolves handle → (instagram_user_id, biography) via web_profile_info.
    Returns (None, "") on failure. Only called once per artist lifetime.
    """
    resp = _ig_get(
        s,
        "https://i.instagram.com/api/v1/users/web_profile_info/",
        params={"username": handle},
    )
    if resp.status_code == 429:
        raise requests.HTTPError(response=resp)
    if resp.status_code == 404:
        return None, ""
    resp.raise_for_status()
    user = (resp.json().get("data") or {}).get("user") or resp.json().get("user") or {}
    uid = user.get("id") or user.get("pk")
    bio = user.get("biography") or ""
    return (str(uid) if uid else None), bio


def check_artist(
    handle: str,
    session_cookie: str = "",
    user_agent: str = "",
    instagram_user_id: str | None = None,
) -> dict[str, Any]:
    """
    Returns:
      {"status": "ok"|"hit"|"error", "hits": [...], "error": "...",
       "breakage": bool, "instagram_user_id": str|None}
    instagram_user_id is populated when newly resolved so the caller can persist it.
    breakage=True means the session is invalid/banned (not a transient issue).
    """
    if not session_cookie:
        return {"status": "error", "error": "Instagram session required", "breakage": True, "instagram_user_id": None}

    s = get_ig_session(session_cookie)
    hits = []
    resolved_user_id = instagram_user_id

    try:
        bio = ""

        if not resolved_user_id:
            # First time seeing this artist — resolve via web_profile_info (only once ever).
            resolved_user_id, bio = _resolve_user_id(s, handle)
            if resolved_user_id is None:
                return {
                    "status": "error",
                    "error": f"Profile @{handle} not found",
                    "breakage": True,
                    "instagram_user_id": None,
                }
            time.sleep(random.uniform(*_INTER_REQUEST_DELAY))
        else:
            # We have the user_id — use the pure mobile endpoint, no web calls.
            info = _ig_get(s, f"https://i.instagram.com/api/v1/users/{resolved_user_id}/info/")
            if info.status_code == 429:
                raise requests.HTTPError(response=info)
            info.raise_for_status()
            bio = (info.json().get("user") or {}).get("biography") or ""
            time.sleep(random.uniform(*_INTER_REQUEST_DELAY))

        bio_kw = _find_keywords(bio)
        if bio_kw:
            hits.append({
                "keyword": bio_kw,
                "post_url": f"https://www.instagram.com/{handle}/",
                "caption_snippet": bio[:200],
            })

        feed = _ig_get(
            s,
            f"https://i.instagram.com/api/v1/feed/user/{resolved_user_id}/",
            params={"count": 12},
        )
        if feed.status_code == 429:
            raise requests.HTTPError(response=feed)
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

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status in (401, 403):
            invalidate_ig_session(session_cookie)
            return {"status": "error", "error": "Instagram session expired or invalid", "breakage": True, "instagram_user_id": resolved_user_id}
        if status == 429:
            return {"status": "error", "error": "Rate limited — try again later", "breakage": False, "instagram_user_id": resolved_user_id, "rate_limited": True}
        return {"status": "error", "error": f"HTTP {status}: {e}", "breakage": False, "instagram_user_id": resolved_user_id}
    except requests.Timeout:
        return {"status": "error", "error": "Request timed out", "breakage": False, "instagram_user_id": resolved_user_id}
    except Exception as e:
        return {"status": "error", "error": str(e), "breakage": False, "instagram_user_id": resolved_user_id}

    return {"status": "hit" if hits else "ok", "hits": hits, "instagram_user_id": resolved_user_id}


def _user_id_from_cookie(session_cookie: str) -> str:
    """Extracts the numeric Instagram user ID encoded at the start of the sessionid."""
    return session_cookie.split("%")[0].split(":")[0]


def iter_timeline_posts(session_cookie: str, hours_back: int = 48, status_cb=None):
    """
    Yields posts from the chronological Instagram following feed in real time.
    Uses a headless browser to load /?variant=following and intercepts
    the API responses to extract post data.
    Each yielded item: {"username", "caption", "post_url", "taken_at"}
    status_cb(message) is called with human-readable progress strings during the fetch.
    Posts are yielded as they arrive from each scroll, not after the full session.
    """
    import queue
    import threading
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    q: queue.Queue = queue.Queue()

    def _run():
        try:
            _fetch_following_posts_sync(session_cookie, cutoff, status_cb=status_cb, post_cb=q.put)
        except Exception as e:
            logger.error("Playwright thread error: %s", e)
        finally:
            q.put(None)  # sentinel

    threading.Thread(target=_run, daemon=True).start()

    while True:
        post = q.get()
        if post is None:
            break
        yield post


def _fetch_following_posts_sync(session_cookie: str, cutoff, status_cb=None, post_cb=None) -> None:
    from playwright.sync_api import sync_playwright
    from datetime import datetime, timezone

    def status(msg: str):
        logger.info("Playwright: %s", msg)
        if status_cb:
            status_cb(msg)

    seen_codes: set[str] = set()
    total_count = [0]

    def _extract_posts_from_json(obj) -> list[dict]:
        results = []
        if isinstance(obj, dict):
            taken_at = obj.get("taken_at")
            user = obj.get("user") or {}
            username = user.get("username") or obj.get("username") or ""
            code = obj.get("code") or obj.get("shortcode") or ""
            if taken_at and username and code:
                cap_obj = obj.get("caption") or {}
                caption = cap_obj.get("text") if isinstance(cap_obj, dict) else (cap_obj or "")
                results.append({
                    "username": username,
                    "caption": caption or "",
                    "post_url": f"https://www.instagram.com/p/{code}/",
                    "taken_at": datetime.fromtimestamp(int(taken_at), tz=timezone.utc),
                    "code": code,
                })
            for v in obj.values():
                results.extend(_extract_posts_from_json(v))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(_extract_posts_from_json(item))
        return results

    def handle_response(response):
        url = response.url
        if "instagram.com" not in url:
            return
        if not any(x in url for x in ("graphql", "api/v1/feed", "api/v1/user")):
            return
        try:
            body = response.json()
            found = 0
            for post in _extract_posts_from_json(body):
                if post["code"] not in seen_codes and post["taken_at"] >= cutoff:
                    seen_codes.add(post["code"])
                    total_count[0] += 1
                    found += 1
                    if post_cb:
                        post_cb(post)
            if found:
                logger.info("Playwright: +%d posts from response (total %d)", found, total_count[0])
        except Exception as e:
            logger.debug("Playwright: could not parse response: %s", e)

    status("Launching browser")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        ctx.add_cookies([{
            "name": "sessionid",
            "value": session_cookie,
            "domain": ".instagram.com",
            "path": "/",
            "secure": True,
        }])

        page = ctx.new_page()
        page.on("response", handle_response)

        status("Loading Instagram following feed...")
        try:
            page.goto("https://www.instagram.com/?variant=following", wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.warning("Playwright: goto error (%s), continuing", e)

        page.wait_for_timeout(3000)
        title = page.title()
        status(f"Page loaded: {title!r} — {total_count[0]} posts so far")

        prev_count = 0
        stall_count = 0
        for i in range(30):
            status(f"Scroll {i + 1} — {total_count[0]} posts seen")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            if total_count[0] == prev_count:
                stall_count += 1
                if stall_count >= 3:
                    status(f"No new posts after 3 scrolls — stopping at {total_count[0]} posts")
                    break
            else:
                stall_count = 0
            prev_count = total_count[0]

        status(f"Done — {total_count[0]} posts collected")
        browser.close()


def iter_following(session_cookie: str):
    """
    Yields (username, total) tuples where total is from the first page.
    Uses Instagram's private mobile API, which is not subject to the web GraphQL breakage.
    """
    s = get_ig_session(session_cookie)
    user_id = _user_id_from_cookie(session_cookie)

    info = _ig_get(s, f"https://i.instagram.com/api/v1/users/{user_id}/info/")
    info.raise_for_status()
    total = info.json().get("user", {}).get("following_count", 0)

    cursor = None
    while True:
        params: dict = {"count": 200}
        if cursor:
            params["max_id"] = cursor
        resp = _ig_get(
            s,
            f"https://i.instagram.com/api/v1/friendships/{user_id}/following/",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        for u in data.get("users", []):
            yield u["username"], total
        cursor = data.get("next_max_id")
        if not cursor:
            break
        time.sleep(0.5)

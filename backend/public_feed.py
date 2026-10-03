# ABOUTME: Reads public Instagram profiles and posts in headless Chromium with no login.
# ABOUTME: Replaces the logged-in feed scan, whose daily automated session got the account locked.

import faulthandler
import logging
import os
import random
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

PACE_SECONDS = (3.0, 7.0)  # between page loads; slow on purpose
STALL_SECONDS = 120  # no progress for this long means a page hung and the scan is abandoned
PAGE_TIMEOUT_MS = 30000

# Profile outcomes. BLOCKED/ERROR say something about Instagram or the network;
# the rest say something about the account and are expected for a few handles.
OK = "ok"
PRIVATE = "private"
RESTRICTED = "restricted"  # age-gated; needs a login to view
UNAVAILABLE = "unavailable"  # deleted, renamed or banned
EMPTY = "empty"  # readable but nothing posted, or a layout we didn't recognise
BLOCKED = "blocked"  # 429 / 401 / 403 / redirected to the login page
ERROR = "error"  # navigation failed or timed out
FAILURE_OUTCOMES = {BLOCKED, ERROR}

_CODE_RE = re.compile(r"/(?:p|reel)/([A-Za-z0-9_-]{8,14})")
_DATE_RE = re.compile(r"\bon ([A-Z][a-z]+ \d{1,2}, \d{4})")
_OG_CAPTION_RE = re.compile(r': "([\s\S]*)"\.?\s*$')
_GRID_SELECTOR = 'a[href*="/p/"], a[href*="/reel/"]'
_GRID_JS = "els => els.map(e => ({href: e.getAttribute('href'), alt: (e.querySelector('img') || {}).alt || ''}))"


@dataclass
class Tile:
    code: str
    url: str
    posted_on: datetime | None  # date only — Instagram's alt text gives no time of day


@dataclass
class ProfileRead:
    outcome: str
    tiles: list[Tile]


@dataclass
class PostRead:
    caption: str
    posted_on: datetime | None


def parse_date(text: str) -> datetime | None:
    """Last 'on Month D, YYYY' in the text. Last, because display names can contain ' on '."""
    matches = _DATE_RE.findall(text or "")
    if not matches:
        return None
    try:
        return datetime.strptime(matches[-1], "%B %d, %Y")
    except ValueError:
        return None


def parse_og_description(desc: str) -> PostRead:
    """og:description reads '<likes>, <comments> - <handle> on <date>: "<caption>".'"""
    desc = desc or ""
    match = _OG_CAPTION_RE.search(desc)
    if not match:
        return PostRead(caption=desc, posted_on=parse_date(desc))
    # Date only from the header before the caption, so a caption saying "on March 3, 2020"
    # can't be mistaken for the post date.
    return PostRead(caption=match.group(1), posted_on=parse_date(desc[: match.start()]))


def parse_tiles(handle: str, raw: list[dict]) -> list[Tile]:
    """Posts this profile owns, newest-pinned order as Instagram renders them, deduped by code."""
    owned_prefix = f"/{handle.lower()}/"
    tiles: dict[str, Tile] = {}
    for item in raw:
        href = item.get("href") or ""
        if not href.lower().startswith(owned_prefix):
            continue  # suggested accounts and other people's links
        match = _CODE_RE.search(href)
        if not match or match.group(1) in tiles:
            continue
        code = match.group(1)
        tiles[code] = Tile(code=code, url=f"https://www.instagram.com{href}", posted_on=parse_date(item.get("alt", "")))
    return list(tiles.values())


def classify_empty(status: int, title: str, page_text: str) -> str:
    if "This profile is private" in page_text:
        return PRIVATE
    if "Restricted profile" in page_text:
        return RESTRICTED
    if status == 404 or "isn't available" in title:
        return UNAVAILABLE
    return EMPTY


class PublicSession:
    """One headless browser for a whole scan. Paces itself and guards against hung pages."""

    def __init__(self, hard_exit: bool = False, on_stall: Callable[[str], None] | None = None):
        # hard_exit=True is for the cron container, where a hung scan must die so Railway
        # sees it finish. In the web process it must stay False: os._exit would kill the app.
        self._hard_exit = hard_exit
        self._on_stall = on_stall
        self._beat_at = time.time()
        self._step = "starting"
        self._first_request = True
        self._closed = threading.Event()

    def __enter__(self) -> "PublicSession":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = self._browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
        self._page = ctx.new_page()
        self._page.set_default_timeout(20000)
        self._beat("browser ready")
        threading.Thread(target=self._watch, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self._closed.set()
        try:
            self._browser.close()
        finally:
            self._pw.stop()

    def _beat(self, step: str) -> None:
        self._beat_at = time.time()
        self._step = step

    def _watch(self) -> None:
        # Playwright's evaluate/title calls take no timeout, so one stuck page blocks forever.
        # A silent zombie scan is the worst failure here — it never alerts — so surface it.
        while not self._closed.wait(10):
            if time.time() - self._beat_at <= STALL_SECONDS:
                continue
            logger.error("WATCHDOG: no progress for %ds at: %s", STALL_SECONDS, self._step)
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            if self._on_stall:
                try:
                    self._on_stall(self._step)
                except Exception:
                    logger.exception("stall notification failed")
            if self._hard_exit:
                sys.stderr.flush()
                os._exit(2)
            return

    def _pace(self) -> None:
        if self._first_request:
            self._first_request = False
            return
        time.sleep(random.uniform(*PACE_SECONDS))

    def profile(self, handle: str) -> ProfileRead:
        self._pace()
        self._beat(f"profile @{handle}")
        page = self._page
        try:
            resp = page.goto(f"https://www.instagram.com/{handle}/", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        except Exception as e:
            logger.warning("profile @%s navigation failed: %s", handle, type(e).__name__)
            return ProfileRead(ERROR, [])
        status = resp.status if resp else 0
        if status in (401, 403, 429) or "/accounts/login" in page.url:
            return ProfileRead(BLOCKED, [])

        try:
            page.wait_for_selector(_GRID_SELECTOR, timeout=8000)
        except Exception:
            pass  # private/restricted/empty profiles never render a grid; classified below
        try:
            tiles = parse_tiles(handle, page.eval_on_selector_all(_GRID_SELECTOR, _GRID_JS))
            if tiles:
                return ProfileRead(OK, tiles)
            try:
                page_text = page.locator("main").inner_text(timeout=3000)
            except Exception:
                page_text = ""
            return ProfileRead(classify_empty(status, page.title(), page_text), [])
        except Exception as e:
            logger.warning("profile @%s read failed: %s", handle, type(e).__name__)
            return ProfileRead(ERROR, [])
        finally:
            self._beat(f"profile @{handle} done")

    def post(self, tile: Tile) -> PostRead | None:
        """Caption and date of one post, or None if it couldn't be read (retry next scan)."""
        self._pace()
        self._beat(f"post {tile.code}")
        try:
            self._page.goto(tile.url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            desc = self._page.locator('meta[property="og:description"]').first.get_attribute("content", timeout=5000)
        except Exception as e:
            logger.warning("post %s read failed: %s", tile.code, type(e).__name__)
            return None
        finally:
            self._beat(f"post {tile.code} done")
        if not desc or not desc.strip():
            return None
        return parse_og_description(desc)

# ABOUTME: APScheduler setup for the daily Instagram check job.
# ABOUTME: Runs check_all_artists at the configured UTC hour each day.

import logging
import queue as sync_queue
import traceback
from datetime import datetime, timezone
from typing import Callable

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

import models
import notifier
import scraper
from config import settings
from crypto import decrypt
from database import SessionLocal

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()

class _EmitLogHandler(logging.Handler):
    """Forwards log records to the SSE stream as log events."""
    def __init__(self, emit_fn: Callable[[dict], None]):
        super().__init__()
        self._emit = emit_fn

    def emit(self, record: logging.LogRecord):
        try:
            self._emit({"type": "log", "level": record.levelname, "message": self.format(record)})
        except Exception:
            pass


def check_all_artists(
    emit: Callable[[dict], None] | None = None,
    user_id_filter: int | None = None,
) -> None:
    """
    Scan the user's Instagram following feed (timeline) for booking keywords.
    One timeline fetch covers all followed artists at once — no per-profile API calls.
    """
    log_handler: _EmitLogHandler | None = None
    if emit:
        log_handler = _EmitLogHandler(emit)
        log_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logging.getLogger().addHandler(log_handler)

    logger.info("Starting timeline check run")
    db: Session = SessionLocal()
    try:
        # Collect users to check (supports user_id_filter for manual "Check now")
        user_ids_to_check = []
        if user_id_filter is not None:
            user_ids_to_check = [user_id_filter]
        else:
            user_ids_to_check = [uid for (uid,) in db.query(models.User.id).all()]

        for uid in user_ids_to_check:
            user = db.get(models.User, uid)
            if not user or not user.instagram_session_cookie:
                continue

            try:
                session_cookie = decrypt(user.instagram_session_cookie)
            except Exception:
                continue

            # Build handle → artist map for quick lookup
            artists_by_handle: dict[str, models.Artist] = {
                a.handle: a
                for a in db.query(models.Artist).filter_by(user_id=uid, active=True).all()
            }
            if not artists_by_handle:
                if emit:
                    emit({"type": "done", "total": 0})
                continue

            if emit:
                emit({"type": "start", "watching": len(artists_by_handle)})

            # hits_by_handle: handle -> list of hit dicts
            hits_by_handle: dict[str, list[dict]] = {}
            # last_post_by_handle: handle -> most recent post seen (url, taken_at)
            last_post_by_handle: dict[str, dict] = {}
            # oldest post seen across the whole scan (to report coverage)
            oldest_post: dict | None = None
            posts_scanned = 0

            def _status_cb(msg: str):
                if emit:
                    emit({"type": "status", "message": msg})

            try:
                for post in scraper.iter_timeline_posts(session_cookie, status_cb=_status_cb):
                    posts_scanned += 1
                    if oldest_post is None or post["taken_at"] < oldest_post["taken_at"]:
                        oldest_post = post
                    handle = post["username"]
                    if emit:
                        emit({
                            "type": "scanning",
                            "handle": handle,
                            "taken_at": post["taken_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "caption_snippet": post["caption"][:80].strip(),
                            "watched": handle in artists_by_handle,
                        })
                    if handle not in artists_by_handle:
                        continue
                    existing = last_post_by_handle.get(handle)
                    if not existing or post["taken_at"] > existing["taken_at"]:
                        last_post_by_handle[handle] = post
                    kw = scraper._find_keywords(post["caption"])
                    if kw:
                        hits_by_handle.setdefault(handle, []).append({
                            "keyword": kw,
                            "post_url": post["post_url"],
                            "caption_snippet": post["caption"][:200],
                        })
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status == 429:
                    if emit:
                        emit({"type": "error", "message": "Instagram rate limited the timeline feed — try again later"})
                    return
                raise

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            done = 0
            for handle, artist in artists_by_handle.items():
                hits = hits_by_handle.get(handle, [])
                artist.last_checked_at = now
                last_post = last_post_by_handle.get(handle)
                if last_post:
                    artist.last_post_url = last_post["post_url"]
                    artist.last_post_at = last_post["taken_at"].replace(tzinfo=None)

                if hits:
                    artist.consecutive_errors = 0
                    artist.last_status = "hit"
                    already_seen = {
                        r.post_url
                        for r in db.query(models.CheckResult.post_url)
                        .filter_by(artist_id=artist.id, status="hit")
                        .all()
                        if r.post_url
                    }
                    for hit in hits:
                        if hit.get("post_url") in already_seen:
                            continue
                        db.add(models.CheckResult(
                            artist_id=artist.id,
                            status="hit",
                            keyword_found=hit["keyword"],
                            post_url=hit.get("post_url"),
                            caption_snippet=hit.get("caption_snippet"),
                        ))
                    db.commit()
                else:
                    artist.consecutive_errors = 0
                    artist.last_status = "ok"
                    db.add(models.CheckResult(artist_id=artist.id, status="ok"))
                    db.commit()

                done += 1
                if emit and hits:
                    emit({
                        "type": "result",
                        "handle": handle,
                        "status": "hit",
                        "hits": hits,
                        "error": None,
                        "done": done,
                        "total": len(artists_by_handle),
                    })

            # Collect unnotified hits and mark them notified in one pass
            new_hits_by_handle: dict[str, list[dict]] = {}
            unnotified = (
                db.query(models.CheckResult)
                .join(models.Artist)
                .filter(
                    models.Artist.user_id == uid,
                    models.CheckResult.status == "hit",
                    models.CheckResult.notified == False,  # noqa: E712
                )
                .all()
            )
            for result in unnotified:
                handle = result.artist.handle
                new_hits_by_handle.setdefault(handle, []).append({
                    "keyword": result.keyword_found,
                    "post_url": result.post_url,
                    "caption_snippet": result.caption_snippet,
                })
                result.notified = True
            db.commit()

            if new_hits_by_handle:
                notifier.notify_scan_complete(
                    total_posts=posts_scanned,
                    hits_by_handle=new_hits_by_handle,
                    scanned_to=oldest_post["taken_at"].strftime("%Y-%m-%d %H:%M UTC") if oldest_post else None,
                )

            if emit:
                done_event: dict = {"type": "done", "total": len(artists_by_handle)}
                if oldest_post:
                    done_event["scanned_to"] = oldest_post["taken_at"].strftime("%Y-%m-%dT%H:%M:%SZ")
                    done_event["scanned_to_handle"] = oldest_post["username"]
                    done_event["scanned_to_preview"] = oldest_post["caption"][:120].strip()
                emit(done_event)

    except Exception:
        logger.error("Scheduler run failed: %s", traceback.format_exc())
        notifier.notify_scheduler_error(traceback.format_exc())
        if emit:
            emit({"type": "error", "message": "Check run failed unexpectedly"})
    finally:
        db.close()
        logger.info("Timeline check run complete")
        if log_handler:
            logging.getLogger().removeHandler(log_handler)


def start() -> None:
    _scheduler.add_job(
        check_all_artists,
        trigger="interval",
        hours=settings.check_interval_hours,
        id="timeline_check",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — timeline check every %dh", settings.check_interval_hours)


def stop() -> None:
    _scheduler.shutdown(wait=False)


def trigger_now() -> None:
    import threading
    threading.Thread(target=check_all_artists, daemon=True).start()


def stream_check(user_id: int) -> sync_queue.Queue:
    """Runs a check for the given user's artists and returns a queue of events."""
    import threading
    q: sync_queue.Queue = sync_queue.Queue()
    threading.Thread(
        target=check_all_artists,
        kwargs={"emit": q.put, "user_id_filter": user_id},
        daemon=True,
    ).start()
    return q

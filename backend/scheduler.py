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

def check_all_artists(
    emit: Callable[[dict], None] | None = None,
    user_id_filter: int | None = None,
) -> None:
    """
    Scan the user's Instagram following feed (timeline) for booking keywords.
    One timeline fetch covers all followed artists at once — no per-profile API calls.
    """
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
                emit({"type": "start", "total": len(artists_by_handle)})

            # hits_by_handle: handle -> list of hit dicts
            hits_by_handle: dict[str, list[dict]] = {}

            try:
                for post in scraper.iter_timeline_posts(session_cookie):
                    handle = post["username"]
                    if handle not in artists_by_handle:
                        continue
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

                if hits:
                    artist.consecutive_errors = 0
                    artist.last_status = "hit"
                    for hit in hits:
                        db.add(models.CheckResult(
                            artist_id=artist.id,
                            status="hit",
                            keyword_found=hit["keyword"],
                            post_url=hit.get("post_url"),
                            caption_snippet=hit.get("caption_snippet"),
                        ))
                    db.commit()
                    notifier.notify_hit(handle, hits)
                else:
                    artist.consecutive_errors = 0
                    artist.last_status = "ok"
                    db.add(models.CheckResult(artist_id=artist.id, status="ok"))
                    db.commit()

                done += 1
                if emit:
                    emit({
                        "type": "result",
                        "handle": handle,
                        "status": artist.last_status,
                        "hits": hits,
                        "error": None,
                        "done": done,
                        "total": len(artists_by_handle),
                    })

            if emit:
                emit({"type": "done", "total": len(artists_by_handle)})

    except Exception:
        logger.error("Scheduler run failed: %s", traceback.format_exc())
        notifier.notify_scheduler_error(traceback.format_exc())
        if emit:
            emit({"type": "error", "message": "Check run failed unexpectedly"})
    finally:
        db.close()
        logger.info("Timeline check run complete")


def start() -> None:
    _scheduler.add_job(
        check_all_artists,
        trigger="cron",
        hour=settings.check_hour,
        minute=0,
        id="daily_check",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — daily check at %02d:00 UTC", settings.check_hour)


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

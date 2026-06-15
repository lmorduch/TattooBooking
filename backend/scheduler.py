# ABOUTME: APScheduler setup for the daily Instagram check job.
# ABOUTME: Runs check_all_artists at the configured UTC hour each day.

import logging
import queue as sync_queue
import random
import time
import traceback
from datetime import datetime, timezone
from typing import Callable

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

BREAKAGE_THRESHOLD = 3


def check_all_artists(
    emit: Callable[[dict], None] | None = None,
    user_id_filter: int | None = None,
) -> None:
    """
    Run checks for all active artists (or just one user's if user_id_filter is set).
    Calls emit(event_dict) for each artist result when provided.
    """
    logger.info("Starting daily check run")
    db: Session = SessionLocal()
    try:
        q = db.query(models.Artist).filter_by(active=True)
        if user_id_filter is not None:
            q = q.filter_by(user_id=user_id_filter)
        artists = q.all()
        logger.info("Checking %d active artists", len(artists))

        if emit:
            emit({"type": "start", "total": len(artists)})

        user_artists: dict[int, list[models.Artist]] = {}
        for artist in artists:
            user_artists.setdefault(artist.user_id, []).append(artist)

        done = 0
        for uid, user_artist_list in user_artists.items():
            user = db.get(models.User, uid)
            session_cookie = ""
            user_agent = ""
            if user and user.instagram_session_cookie:
                try:
                    session_cookie = decrypt(user.instagram_session_cookie)
                    user_agent = user.instagram_user_agent or ""
                except Exception:
                    pass
            rate_limited = False
            for artist in user_artist_list:
                if rate_limited:
                    break
                if emit:
                    emit({"type": "checking", "handle": artist.handle, "done": done, "total": len(artists)})
                result = _check_one(db, artist, session_cookie, user_agent)
                done += 1
                if result.get("rate_limited"):
                    rate_limited = True
                    if emit:
                        emit({"type": "error", "message": "Instagram rate limit hit — try again in a few minutes"})
                    break
                if emit:
                    emit({
                        "type": "result",
                        "handle": artist.handle,
                        "status": result["status"],
                        "hits": result.get("hits", []),
                        "error": result.get("error"),
                        "done": done,
                        "total": len(artists),
                    })
                # Pause between artists to stay within Instagram's rate limits.
                # ~200 req/11min window; we use 2 req/artist at 4-7s = safe headroom.
                if done < len(artists):
                    time.sleep(random.uniform(*scraper._INTER_ARTIST_DELAY))

        if emit:
            emit({"type": "done", "total": len(artists)})

    except Exception:
        logger.error("Scheduler run failed: %s", traceback.format_exc())
        notifier.notify_scheduler_error(traceback.format_exc())
        if emit:
            emit({"type": "error", "message": "Check run failed unexpectedly"})
    finally:
        db.close()
        logger.info("Daily check run complete")


def _check_one(db: Session, artist: models.Artist, session_cookie: str = "", user_agent: str = "") -> dict:
    logger.info("Checking @%s", artist.handle)
    result = scraper.check_artist(
        artist.handle, session_cookie, user_agent,
        instagram_user_id=artist.instagram_user_id,
    )
    # Persist the user_id if we just resolved it for the first time
    if result.get("instagram_user_id") and not artist.instagram_user_id:
        artist.instagram_user_id = result["instagram_user_id"]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    artist.last_checked_at = now

    if result["status"] == "error":
        artist.consecutive_errors += 1
        artist.last_status = "error"
        db.add(models.CheckResult(artist_id=artist.id, status="error", error_message=result["error"]))
        db.commit()
        if result.get("breakage") and artist.consecutive_errors >= BREAKAGE_THRESHOLD:
            notifier.notify_breakage(artist.handle, result["error"], artist.consecutive_errors)

    elif result["status"] == "hit":
        artist.consecutive_errors = 0
        artist.last_status = "hit"
        for hit in result["hits"]:
            db.add(models.CheckResult(
                artist_id=artist.id,
                status="hit",
                keyword_found=hit["keyword"],
                post_url=hit.get("post_url"),
                caption_snippet=hit.get("caption_snippet"),
            ))
        db.commit()
        notifier.notify_hit(artist.handle, result["hits"])

    else:
        artist.consecutive_errors = 0
        artist.last_status = "ok"
        db.add(models.CheckResult(artist_id=artist.id, status="ok"))
        db.commit()

    return result


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

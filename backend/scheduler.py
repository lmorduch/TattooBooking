# ABOUTME: APScheduler setup for the daily Instagram check job.
# ABOUTME: Runs check_all_artists at the configured UTC hour each day.

import logging
import traceback
from datetime import datetime, timezone

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

# Consecutive error threshold before we email about breakage
BREAKAGE_THRESHOLD = 3


def check_all_artists() -> None:
    logger.info("Starting daily check run")
    db: Session = SessionLocal()
    try:
        artists = db.query(models.Artist).filter_by(active=True).all()
        logger.info("Checking %d active artists", len(artists))

        # Group artists by user so we can use each user's session cookie
        user_artists: dict[int, list[models.Artist]] = {}
        for artist in artists:
            user_artists.setdefault(artist.user_id, []).append(artist)

        for user_id, user_artist_list in user_artists.items():
            user = db.get(models.User, user_id)
            session_cookie = ""
            user_agent = ""
            if user and user.instagram_session_cookie:
                try:
                    session_cookie = decrypt(user.instagram_session_cookie)
                    user_agent = user.instagram_user_agent or ""
                except Exception:
                    pass
            for artist in user_artist_list:
                _check_one(db, artist, session_cookie, user_agent)

    except Exception as e:
        logger.error("Scheduler run failed: %s", traceback.format_exc())
        notifier.notify_scheduler_error(traceback.format_exc())
    finally:
        db.close()
        logger.info("Daily check run complete")


def _check_one(db: Session, artist: models.Artist, session_cookie: str = "", user_agent: str = "") -> None:
    logger.info("Checking @%s", artist.handle)
    result = scraper.check_artist(artist.handle, session_cookie, user_agent)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    artist.last_checked_at = now

    if result["status"] == "error":
        artist.consecutive_errors += 1
        artist.last_status = "error"

        check = models.CheckResult(
            artist_id=artist.id,
            status="error",
            error_message=result["error"],
        )
        db.add(check)
        db.commit()

        if result.get("breakage") and artist.consecutive_errors >= BREAKAGE_THRESHOLD:
            notifier.notify_breakage(artist.handle, result["error"], artist.consecutive_errors)

    elif result["status"] == "hit":
        artist.consecutive_errors = 0
        artist.last_status = "hit"

        for hit in result["hits"]:
            check = models.CheckResult(
                artist_id=artist.id,
                status="hit",
                keyword_found=hit["keyword"],
                post_url=hit.get("post_url"),
                caption_snippet=hit.get("caption_snippet"),
            )
            db.add(check)

        db.commit()
        notifier.notify_hit(artist.handle, result["hits"])

    else:  # ok
        artist.consecutive_errors = 0
        artist.last_status = "ok"

        check = models.CheckResult(
            artist_id=artist.id,
            status="ok",
        )
        db.add(check)
        db.commit()


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
    """Run the check immediately (used by the manual trigger endpoint)."""
    import threading
    t = threading.Thread(target=check_all_artists, daemon=True)
    t.start()

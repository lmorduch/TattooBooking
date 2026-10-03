# ABOUTME: Scan orchestration: reads each tracked artist's public profile, judges new posts, emails hits.
# ABOUTME: Runs daily from the Railway cron (run_scan.py) and on demand from the app's "Check now".

import logging
import queue as sync_queue
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

import models
import notifier
import public_feed
import scraper
from config import settings
from database import SessionLocal

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()

# A post older than this showing up in the grid is a re-pin or an unarchive, not news.
RECENT_POST_DAYS = 14
# The scan is "blind" when it can't read most profiles. A handful of private or deleted
# accounts is normal and doesn't count; Instagram blocking us does.
BLIND_MIN_PROFILES = 5
BLIND_FAILURE_RATIO = 0.5

_OUTCOME_MESSAGES = {
    public_feed.PRIVATE: "Private profile — can't be read without logging in",
    public_feed.RESTRICTED: "Age-restricted profile — needs a login to view",
    public_feed.UNAVAILABLE: "Profile isn't available — deleted or renamed?",
    public_feed.EMPTY: "No posts found on the profile",
}


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record_scan_run(db: Session, user_id: int, posts_scanned: int, status: str) -> int:
    """Records one scan run; returns how many consecutive runs have now come back blind."""
    db.add(models.ScanRun(user_id=user_id, posts_scanned=posts_scanned, status=status))
    db.commit()
    if status != "empty":
        return 0

    streak = 0
    recent = (
        db.query(models.ScanRun)
        .filter_by(user_id=user_id)
        .order_by(models.ScanRun.id.desc())
        .limit(60)
        .all()
    )
    for run in recent:
        if run.status != "empty":
            break
        streak += 1
    return streak


def _is_blind(counts: Counter, total: int) -> bool:
    failed = sum(counts[o] for o in public_feed.FAILURE_OUTCOMES)
    return total >= BLIND_MIN_PROFILES and (counts[public_feed.OK] == 0 or failed / total >= BLIND_FAILURE_RATIO)


def _mark_seen(db: Session, artist: models.Artist, seen: set[str], code: str) -> None:
    seen.add(code)
    db.add(models.SeenPost(artist_id=artist.id, code=code))


def _scan_artist(
    db: Session,
    ig: public_feed.PublicSession,
    artist: models.Artist,
    seen: set[str],
    now: datetime,
) -> dict:
    read = ig.profile(artist.handle)
    result: dict = {
        "outcome": read.outcome, "tiles": len(read.tiles), "posts_checked": 0,
        "post_failures": 0, "baselined": False, "hits": [], "newest": None,
    }

    if read.outcome in public_feed.FAILURE_OUTCOMES:
        # Says something about Instagram or the network, not about this artist.
        return result

    artist.last_checked_at = now
    if read.outcome != public_feed.OK:
        artist.last_status = "error"
        artist.consecutive_errors = (artist.consecutive_errors or 0) + 1
        db.add(models.CheckResult(artist_id=artist.id, status="error", error_message=_OUTCOME_MESSAGES[read.outcome]))
        db.commit()
        return result

    dated = [t for t in read.tiles if t.posted_on]
    if dated:
        newest = max(dated, key=lambda t: t.posted_on)
        artist.last_post_url = newest.url
        artist.last_post_at = newest.posted_on
        result["newest"] = newest.posted_on

    cutoff = now - timedelta(days=RECENT_POST_DAYS)
    hits: list[dict] = result["hits"]
    if artist.baselined_at is None:
        # First look at this artist: record what's already up without judging it, so a
        # fresh scan (or a newly added artist) never emails about old posts.
        for tile in read.tiles:
            _mark_seen(db, artist, seen, tile.code)
        artist.baselined_at = now
        result["baselined"] = True
    else:
        for tile in read.tiles:
            if tile.code in seen:
                continue
            if tile.posted_on and tile.posted_on < cutoff:
                _mark_seen(db, artist, seen, tile.code)
                continue
            post = ig.post(tile)
            result["posts_checked"] += 1
            if post is None:
                result["post_failures"] += 1  # left unseen so the next scan tries again
                continue
            _mark_seen(db, artist, seen, tile.code)
            if post.posted_on and post.posted_on < cutoff:
                continue
            keyword = scraper._find_keywords(post.caption)
            if keyword:
                hits.append({"keyword": keyword, "post_url": tile.url, "caption_snippet": post.caption[:200]})

    artist.consecutive_errors = 0
    if hits:
        artist.last_status = "hit"
        for hit in hits:
            db.add(models.CheckResult(
                artist_id=artist.id,
                status="hit",
                keyword_found=hit["keyword"],
                post_url=hit["post_url"],
                caption_snippet=hit["caption_snippet"],
            ))
    else:
        artist.last_status = "ok"
        db.add(models.CheckResult(artist_id=artist.id, status="ok"))
    db.commit()
    return result


def _notify_new_hits(db: Session, uid: int, tiles_total: int) -> None:
    """Emails every hit not yet notified, then marks them notified."""
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
        new_hits_by_handle.setdefault(result.artist.handle, []).append({
            "keyword": result.keyword_found,
            "post_url": result.post_url,
            "caption_snippet": result.caption_snippet,
        })
        result.notified = True
    db.commit()

    if new_hits_by_handle:
        notifier.notify_scan_complete(total_posts=tiles_total, hits_by_handle=new_hits_by_handle, scanned_to=None)


def _scan_user(
    db: Session,
    uid: int,
    artists: list[models.Artist],
    emit: Callable[[dict], None] | None,
    hard_exit: bool,
) -> None:
    started = time.time()
    now = _utcnow()
    total = len(artists)

    seen_by_artist: dict[int, set[str]] = defaultdict(set)
    for artist_id, code in db.query(models.SeenPost.artist_id, models.SeenPost.code).filter(
        models.SeenPost.artist_id.in_([a.id for a in artists])
    ):
        seen_by_artist[artist_id].add(code)

    counts: Counter = Counter()
    tiles_total = posts_checked = post_failures = baselined = hit_count = 0

    def on_stall(step: str) -> None:
        notifier.notify_scheduler_error(
            f"The scan made no progress for {public_feed.STALL_SECONDS}s and was abandoned at: {step}"
        )

    with public_feed.PublicSession(hard_exit=hard_exit, on_stall=on_stall) as ig:
        for i, artist in enumerate(artists, 1):
            if emit:
                emit({"type": "status", "message": f"@{artist.handle} ({i}/{total})"})
            r = _scan_artist(db, ig, artist, seen_by_artist[artist.id], now)

            counts[r["outcome"]] += 1
            tiles_total += r["tiles"]
            posts_checked += r["posts_checked"]
            post_failures += r["post_failures"]
            baselined += r["baselined"]
            hit_count += len(r["hits"])
            logger.info(
                "PROFILE %d/%d @%s outcome=%s tiles=%d posts_checked=%d hits=%d%s",
                i, total, artist.handle, r["outcome"], r["tiles"], r["posts_checked"], len(r["hits"]),
                " baselined" if r["baselined"] else "",
            )

            if emit and r["newest"]:
                emit({
                    "type": "scanning",
                    "handle": artist.handle,
                    "taken_at": r["newest"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "caption_snippet": "",
                    "watched": True,
                })
            if emit and r["hits"]:
                emit({
                    "type": "result", "handle": artist.handle, "status": "hit", "hits": r["hits"],
                    "error": None, "done": i, "total": total,
                })

    outcome_summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    logger.info(
        "SCAN SUMMARY profiles=%d %s tiles=%d posts_checked=%d post_failures=%d baselined=%d hits=%d duration=%ds",
        total, outcome_summary, tiles_total, posts_checked, post_failures, baselined, hit_count, time.time() - started,
    )

    _notify_new_hits(db, uid, tiles_total)

    if _is_blind(counts, total):
        streak = _record_scan_run(db, uid, tiles_total, "empty")
        logger.error("Scan for user %s was blind (%d in a row): %s", uid, streak, outcome_summary)
        if streak == 1 or streak % 7 == 0:
            notifier.notify_scan_blind(
                streak, f"Of {total} profiles, {counts[public_feed.OK]} could be read. Outcomes: {outcome_summary}"
            )
        if emit:
            emit({"type": "error", "message": "Scan could not read most profiles — Instagram may be blocking it."})
        return

    _record_scan_run(db, uid, tiles_total, "ok")
    if emit:
        emit({"type": "done", "total": total})


def check_all_artists(
    emit: Callable[[dict], None] | None = None,
    user_id_filter: int | None = None,
    hard_exit: bool = False,
) -> None:
    """
    Scan every active artist's public Instagram profile for booking keywords. No login is
    involved. hard_exit=True (the cron container) kills the process if a page hangs; leave
    it False inside the web service, where that would take the whole app down.
    """
    log_handler: _EmitLogHandler | None = None
    if emit:
        log_handler = _EmitLogHandler(emit)
        log_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logging.getLogger().addHandler(log_handler)

    logger.info("Starting scan run")
    db: Session = SessionLocal()
    try:
        if user_id_filter is not None:
            user_ids = [user_id_filter]
        else:
            user_ids = [uid for (uid,) in db.query(models.User.id).all()]

        for uid in user_ids:
            artists = (
                db.query(models.Artist)
                .filter_by(user_id=uid, active=True)
                .order_by(models.Artist.handle)
                .all()
            )
            if not artists:
                if emit:
                    emit({"type": "done", "total": 0})
                continue

            if emit:
                emit({"type": "start", "watching": len(artists)})
            _scan_user(db, uid, artists, emit, hard_exit)

    except Exception:
        logger.error("Scheduler run failed: %s", traceback.format_exc())
        notifier.notify_scheduler_error(traceback.format_exc())
        if emit:
            emit({"type": "error", "message": "Check run failed unexpectedly"})
    finally:
        db.close()
        logger.info("Scan run complete")
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
    logger.info("Scheduler started — scan every %dh", settings.check_interval_hours)


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

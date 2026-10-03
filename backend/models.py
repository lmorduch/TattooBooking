# ABOUTME: SQLAlchemy ORM models for users, tracked artists, and check results.
# ABOUTME: Entities: User, Artist, CheckResult, SeenPost, ScanRun.

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    google_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    picture: Mapped[str | None] = mapped_column(String, nullable=True)
    instagram_username: Mapped[str | None] = mapped_column(String, nullable=True)
    instagram_session_cookie: Mapped[str | None] = mapped_column(String, nullable=True)
    instagram_user_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    artists: Mapped[list["Artist"]] = relationship("Artist", back_populates="user")


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    handle: Mapped[str] = mapped_column(String, nullable=False)
    instagram_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_post_url: Mapped[str | None] = mapped_column(String, nullable=True)
    last_post_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Set once the artist's existing posts have been recorded as seen, so a first scan
    # (or a newly added artist) never emails about posts that were already up.
    baselined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 'pending' | 'ok' | 'hit' | 'error'
    last_status: Mapped[str] = mapped_column(String, default="pending")
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="artists")
    check_results: Mapped[list["CheckResult"]] = relationship(
        "CheckResult", back_populates="artist", cascade="all, delete-orphan",
        order_by="CheckResult.checked_at.desc()",
    )
    seen_posts: Mapped[list["SeenPost"]] = relationship(
        "SeenPost", back_populates="artist", cascade="all, delete-orphan",
    )


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(Integer, ForeignKey("artists.id"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # 'ok' | 'hit' | 'error'
    status: Mapped[str] = mapped_column(String, nullable=False)
    keyword_found: Mapped[str | None] = mapped_column(String, nullable=True)
    post_url: Mapped[str | None] = mapped_column(String, nullable=True)
    caption_snippet: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)

    artist: Mapped["Artist"] = relationship("Artist", back_populates="check_results")


class SeenPost(Base):
    """A post the scanner has already looked at, so each post is judged exactly once."""

    __tablename__ = "seen_posts"
    __table_args__ = (UniqueConstraint("artist_id", "code", name="uq_seen_posts_artist_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(Integer, ForeignKey("artists.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    artist: Mapped["Artist"] = relationship("Artist", back_populates="seen_posts")


class ScanRun(Base):
    """One execution of the scan. Exists so a run that quietly reads nothing can be
    distinguished from a run that genuinely had nothing to find."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # Posts visible across all readable profiles in this run.
    posts_scanned: Mapped[int] = mapped_column(Integer, default=0)
    # 'ok' | 'empty' — 'empty' means the run was blind: most profiles could not be read
    status: Mapped[str] = mapped_column(String, nullable=False)

# ABOUTME: SQLAlchemy ORM models for users, tracked artists, and check results.
# ABOUTME: Entities: User, Artist, CheckResult.

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
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

    artist: Mapped["Artist"] = relationship("Artist", back_populates="check_results")

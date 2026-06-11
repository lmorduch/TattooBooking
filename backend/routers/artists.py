# ABOUTME: CRUD routes for managed Instagram artists.
# ABOUTME: Endpoints: list, add, delete, toggle active, get check history, trigger check.

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
import scheduler
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/artists", tags=["artists"])


class ArtistOut(BaseModel):
    id: int
    handle: str
    active: bool
    last_checked_at: datetime | None
    last_status: str
    consecutive_errors: int
    created_at: datetime

    class Config:
        from_attributes = True


class CheckResultOut(BaseModel):
    id: int
    checked_at: datetime
    status: str
    keyword_found: str | None
    post_url: str | None
    caption_snippet: str | None
    error_message: str | None

    class Config:
        from_attributes = True


class AddArtist(BaseModel):
    handle: str


class PatchArtist(BaseModel):
    active: bool | None = None


@router.get("", response_model=list[ArtistOut])
def list_artists(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Artist)
        .filter_by(user_id=current_user["user_id"])
        .order_by(models.Artist.created_at)
        .all()
    )


@router.post("", response_model=ArtistOut, status_code=201)
def add_artist(
    body: AddArtist,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handle = body.handle.lstrip("@").strip().lower()
    existing = (
        db.query(models.Artist)
        .filter_by(user_id=current_user["user_id"], handle=handle)
        .first()
    )
    if existing:
        raise HTTPException(409, f"@{handle} is already in your list")

    artist = models.Artist(user_id=current_user["user_id"], handle=handle)
    db.add(artist)
    db.commit()
    db.refresh(artist)
    return artist


@router.delete("/{artist_id}", status_code=204)
def delete_artist(
    artist_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    artist = db.query(models.Artist).filter_by(
        id=artist_id, user_id=current_user["user_id"]
    ).first()
    if not artist:
        raise HTTPException(404, "Artist not found")
    db.delete(artist)
    db.commit()


@router.patch("/{artist_id}", response_model=ArtistOut)
def patch_artist(
    artist_id: int,
    body: PatchArtist,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    artist = db.query(models.Artist).filter_by(
        id=artist_id, user_id=current_user["user_id"]
    ).first()
    if not artist:
        raise HTTPException(404, "Artist not found")
    if body.active is not None:
        artist.active = body.active
    db.commit()
    db.refresh(artist)
    return artist


@router.get("/{artist_id}/checks", response_model=list[CheckResultOut])
def get_checks(
    artist_id: int,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    artist = db.query(models.Artist).filter_by(
        id=artist_id, user_id=current_user["user_id"]
    ).first()
    if not artist:
        raise HTTPException(404, "Artist not found")
    return (
        db.query(models.CheckResult)
        .filter_by(artist_id=artist_id)
        .order_by(models.CheckResult.checked_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/run", status_code=202)
def trigger_check(current_user: dict = Depends(get_current_user)):
    """Manually kick off a check run in the background."""
    scheduler.trigger_now()
    return {"message": "Check run started"}

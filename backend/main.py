# ABOUTME: FastAPI application entry point.
# ABOUTME: Mounts routers, handles auth, starts scheduler on startup.

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import models
import scheduler
from auth import COOKIE_NAME, FRONTEND_URL, exchange_code, get_current_user, login_url, make_jwt
from crypto import decrypt, encrypt
from database import Base, engine, get_db
from routers import artists

Base.metadata.create_all(bind=engine)

with engine.connect() as _conn:
    from sqlalchemy import text
    _conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_username VARCHAR"))
    _conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_password VARCHAR"))
    _conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_session_cookie VARCHAR"))
    _conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Tattoo Tracker", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(artists.router)


# ── Auth routes ──────────────────────────────────────────────────────────────

@app.get("/auth/login")
def auth_login():
    return RedirectResponse(login_url())


@app.get("/auth/callback")
async def auth_callback(code: str, db: Session = Depends(get_db)):
    user_info = await exchange_code(code)

    user = db.query(models.User).filter_by(google_id=user_info["sub"]).first()
    if user:
        user.email = user_info.get("email", "")
        user.name = user_info.get("name", "")
        user.picture = user_info.get("picture")
    else:
        user = models.User(
            google_id=user_info["sub"],
            email=user_info.get("email", ""),
            name=user_info.get("name", ""),
            picture=user_info.get("picture"),
        )
        db.add(user)
    db.commit()
    db.refresh(user)

    redirect = RedirectResponse(FRONTEND_URL)
    redirect.set_cookie(
        key=COOKIE_NAME,
        value=make_jwt(user.id),
        httponly=True,
        samesite="lax",
        secure=os.getenv("BACKEND_URL", "").startswith("https"),
        max_age=30 * 24 * 60 * 60,
    )
    return redirect


@app.get("/auth/me")
def auth_me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(models.User, current_user["user_id"])
    if not user:
        from fastapi import HTTPException
        raise HTTPException(404, "User not found")
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "has_instagram": bool(user.instagram_session_cookie),
        "instagram_username": user.instagram_username,
    }


class _MeUpdate(BaseModel):
    instagram_session_cookie: str | None = None


@app.put("/auth/me")
def update_me(
    body: _MeUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi import HTTPException
    import scraper
    user = db.get(models.User, current_user["user_id"])
    if not user:
        raise HTTPException(404, "User not found")
    if body.instagram_session_cookie is not None:
        cookie = body.instagram_session_cookie.strip() or None
        if cookie:
            # Verify the cookie and get the username
            username = scraper.verify_session_cookie(cookie)
            if not username:
                raise HTTPException(400, "Session cookie is invalid or expired")
            user.instagram_username = username
            user.instagram_session_cookie = encrypt(cookie)
        else:
            user.instagram_session_cookie = None
            user.instagram_username = None
        db.commit()
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "has_instagram": bool(user.instagram_session_cookie),
        "instagram_username": user.instagram_username,
    }


@app.post("/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Serve frontend (production) ───────────────────────────────────────────────

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

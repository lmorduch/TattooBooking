# ABOUTME: Schema migrations, shared by the web service (on startup) and the scan cron.
# ABOUTME: create_all for new tables plus ADD COLUMN IF NOT EXISTS for new columns on old ones.

from sqlalchemy import text

import models  # noqa: F401  — registers every table on Base before create_all
from database import Base, engine


def run_migrations() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_username VARCHAR"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_password VARCHAR"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_session_cookie VARCHAR"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_user_agent VARCHAR"))
        conn.execute(text("ALTER TABLE artists ADD COLUMN IF NOT EXISTS instagram_user_id VARCHAR"))
        conn.execute(text("ALTER TABLE artists ADD COLUMN IF NOT EXISTS last_post_url VARCHAR"))
        conn.execute(text("ALTER TABLE artists ADD COLUMN IF NOT EXISTS last_post_at TIMESTAMP"))
        conn.execute(text("ALTER TABLE artists ADD COLUMN IF NOT EXISTS baselined_at TIMESTAMP"))
        conn.execute(text("ALTER TABLE check_results ADD COLUMN IF NOT EXISTS notified BOOLEAN DEFAULT FALSE"))
        conn.commit()

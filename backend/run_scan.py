# ABOUTME: One-shot entrypoint for the Railway cron service.
# ABOUTME: Runs a single timeline scan for all users, then exits.

import logging

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

import models  # noqa: F401  — registers tables on Base before create_all
import scheduler
from database import Base, engine

if __name__ == "__main__":
    # The web service runs migrations on startup, but it sleeps when idle, so the cron
    # can be first to touch a newly added table. create_all is a no-op once it exists.
    Base.metadata.create_all(bind=engine)
    scheduler.check_all_artists()

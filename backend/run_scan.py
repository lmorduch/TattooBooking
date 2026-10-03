# ABOUTME: One-shot entrypoint for the Railway cron service.
# ABOUTME: Runs a single scan of every tracked artist's public profile, then exits.

import logging

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

import scheduler
from migrations import run_migrations

if __name__ == "__main__":
    # The web service runs migrations on startup, but it sleeps when idle, so the cron
    # can be first to touch a newly added table or column. Safe to repeat.
    run_migrations()
    # hard_exit: if a page hangs the process must die, or Railway sees a scan that never finishes.
    scheduler.check_all_artists(hard_exit=True)

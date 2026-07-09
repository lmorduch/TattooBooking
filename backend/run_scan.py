# ABOUTME: One-shot entrypoint for the Railway cron service.
# ABOUTME: Runs a single timeline scan for all users, then exits.

import logging

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

import scheduler

if __name__ == "__main__":
    scheduler.check_all_artists()

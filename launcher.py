"""
Ark - Launcher script.
Starts both the Slack bot and the reminder scheduler as separate threads.
Using threads instead of processes for better Railway compatibility.
"""

import sys
import os
import logging
import threading

# Add ark directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ark-launcher")


def run_bot():
    """Run the Slack bot."""
    from bot import main as bot_main
    bot_main()


def run_scheduler():
    """Run the reminder scheduler."""
    from scheduler import main as scheduler_main
    scheduler_main()


if __name__ == "__main__":
    logger.info("Starting Ark with bot and scheduler...")

    # Start scheduler in background thread (daemon so it exits when main thread exits)
    scheduler_thread = threading.Thread(target=run_scheduler, name="ark-scheduler", daemon=True)
    scheduler_thread.start()
    logger.info("Scheduler thread started")

    # Run bot in main thread (this blocks)
    logger.info("Starting bot in main thread...")
    run_bot()

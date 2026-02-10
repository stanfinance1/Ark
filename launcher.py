"""
Ark - Launcher script.
Starts both the Slack bot and the reminder scheduler as separate processes.
"""

import sys
import os
import logging
from multiprocessing import Process

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

    # Start bot process
    bot_process = Process(target=run_bot, name="ark-bot")
    bot_process.start()

    # Start scheduler process
    scheduler_process = Process(target=run_scheduler, name="ark-scheduler")
    scheduler_process.start()

    logger.info("Both processes started. Waiting...")

    # Wait for both processes
    try:
        bot_process.join()
        scheduler_process.join()
    except KeyboardInterrupt:
        logger.info("Stopping Ark...")
        bot_process.terminate()
        scheduler_process.terminate()
        bot_process.join()
        scheduler_process.join()
        logger.info("Ark stopped.")

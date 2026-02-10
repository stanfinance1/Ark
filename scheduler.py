"""
Ark - Reminder scheduler.
Runs continuously in the background, checking for due reminders and sending them to Slack.
"""

import os
import sys
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# Add ark directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load env vars
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from slack_sdk import WebClient
from reminders import ReminderManager, USER_TIMEZONE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ark-scheduler")

# Slack client
slack_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
if not slack_token:
    logger.error("SLACK_BOT_TOKEN not set!")
    sys.exit(1)

slack_client = WebClient(token=slack_token)


def fire_reminder(reminder: dict):
    """Send a reminder to Slack."""
    try:
        message = reminder["message"]
        user_id = reminder["user_id"]
        channel = reminder["channel"]
        thread_ts = reminder.get("thread_ts")

        # Format message with @mention
        slack_message = f"<@{user_id}> Reminder: {message}"

        # Send to channel or thread
        slack_client.chat_postMessage(
            channel=channel,
            text=slack_message,
            thread_ts=thread_ts,
        )

        logger.info(f"Sent reminder {reminder['id']} to {user_id} in {channel}: {message}")
        return True

    except Exception as e:
        logger.error(f"Failed to send reminder {reminder['id']}: {e}")
        return False


def main():
    """Main scheduler loop - checks for due reminders every 30 seconds."""
    logger.info(f"Ark reminder scheduler starting... (timezone: {USER_TIMEZONE})")
    manager = ReminderManager()

    while True:
        try:
            # Get all due reminders
            due_reminders = manager.get_due_reminders()

            if due_reminders:
                now = datetime.now(USER_TIMEZONE)
                logger.info(f"Found {len(due_reminders)} due reminder(s) at {now.strftime('%Y-%m-%d %I:%M %p %Z')}")

            for reminder in due_reminders:
                # Fire the reminder
                success = fire_reminder(reminder)

                if success:
                    # Update the reminder (mark completed or schedule next occurrence)
                    manager.update_after_fire(reminder["id"])

            # Sleep for 30 seconds before checking again
            time.sleep(30)

        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}", exc_info=True)
            # Sleep and continue on error
            time.sleep(30)


if __name__ == "__main__":
    main()

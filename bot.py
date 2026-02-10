"""
Ark - Slack Bot for HNY Plus, Inc.
Always-on AI operations assistant with tool execution capabilities.

Run with: python bot.py
"""

import os
import re
import sys
import logging
import urllib.request
import time

# Add ark directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

# Load environment variables from parent .env (local dev) or Railway env vars (production)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ark")


def _clean_mention(text: str) -> str:
    """Remove @Ark mention from message text."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def _download_slack_files(files: list) -> list:
    """Download files attached to a Slack message to tmp/uploads/."""
    upload_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "tmp", "uploads"
    )
    os.makedirs(upload_dir, exist_ok=True)

    token = os.environ["SLACK_BOT_TOKEN"].strip()
    downloaded = []

    for f in files:
        url = f.get("url_private_download")
        name = f.get("name", "unknown_file")
        if not url:
            continue

        # Prefix with timestamp to avoid collisions
        safe_name = f"{int(time.time())}_{name}"
        save_path = os.path.join(upload_dir, safe_name)

        try:
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(req) as resp:
                with open(save_path, "wb") as out:
                    out.write(resp.read())

            downloaded.append({
                "name": name,
                "path": save_path,
                "size": f.get("size", 0),
                "mimetype": f.get("mimetype", ""),
            })
            logger.info(f"Downloaded file: {name} -> {save_path}")
        except Exception as e:
            logger.error(f"Failed to download {name}: {e}")

    return downloaded


def _handle_message(event, say, client):
    """Core message handler - processes user message through Claude and responds."""
    from brain import think

    text = event.get("text", "")

    # Ignore bot messages (avoid infinite loops)
    if event.get("bot_id"):
        return

    # Skip if no text AND no files
    if not text and not event.get("files"):
        return

    clean_text = _clean_mention(text)

    # Download any files attached to the message
    attached_files = event.get("files", [])
    downloaded = []
    if attached_files:
        downloaded = _download_slack_files(attached_files)

    # If no text but files were attached, set a default prompt
    if not clean_text and not downloaded:
        return
    if not clean_text and downloaded:
        clean_text = "I've shared some files with you. Please take a look."

    # Append file context so Claude knows what was uploaded
    if downloaded:
        file_lines = ["\n\n[User attached files (downloaded to server):]"]
        for d in downloaded:
            file_lines.append(f"- {d['name']} -> {d['path']} ({d['mimetype']})")
        file_lines.append(
            "Use read_file for text/CSV files, or run_python with pandas for Excel files."
        )
        clean_text += "\n".join(file_lines)

    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    user = event.get("user", "unknown")

    logger.info(f"Message from {user} in {channel}: {clean_text[:100]}...")

    # Build Slack context for tool execution (file uploads, etc.)
    slack_context = {
        "client": client,
        "channel": channel,
        "thread_ts": thread_ts,
    }

    try:
        # Send "thinking" reaction
        try:
            client.reactions_add(
                channel=channel,
                timestamp=event["ts"],
                name="brain",
            )
        except Exception:
            pass  # Reaction might fail if already added

        # Process through Claude
        result = think(clean_text, channel, thread_ts, slack_context)

        # Remove "thinking" reaction
        try:
            client.reactions_remove(
                channel=channel,
                timestamp=event["ts"],
                name="brain",
            )
        except Exception:
            pass

        # Reply in thread
        if result["text"]:
            # Slack has a 4000 char limit per message - split if needed
            response_text = result["text"]
            while response_text:
                chunk = response_text[:3900]
                response_text = response_text[3900:]
                say(text=chunk, thread_ts=thread_ts)

        logger.info(f"Replied to {user} ({len(result['text'])} chars)")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        say(
            text=f"Sorry, I hit an error: {str(e)[:200]}",
            thread_ts=thread_ts,
        )


def main():
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    logger.info("Starting Ark...")

    app = App(
        token=os.environ["SLACK_BOT_TOKEN"].strip(),
        signing_secret=os.environ["SLACK_SIGNING_SECRET"].strip(),
    )

    @app.event("app_mention")
    def handle_mention(event, say, client):
        _handle_message(event, say, client)

    @app.event("message")
    def handle_dm(event, say, client):
        if event.get("channel_type") == "im":
            _handle_message(event, say, client)

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"].strip())
    logger.info("Ark is online. Listening for messages.")
    handler.start()


if __name__ == "__main__":
    main()

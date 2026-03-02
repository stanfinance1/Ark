"""
Ark - Slack Bot for HNY Plus, Inc.
Always-on AI operations assistant with tool execution capabilities.

Responds to:
  - @Ark mentions (app_mention event)
  - Direct messages
  - Channel messages that mention "ark" by name
  - Threads Ark has already participated in

Run with: python bot.py
"""

import os
import re
import sys
import logging
import urllib.request
import time
from collections import defaultdict

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

# ---------------------------------------------------------------------------
# Ark identity (populated at startup in main())
# ---------------------------------------------------------------------------
_ark_user_id = None  # Ark's Slack user ID (e.g. "U08XXXXXXX")
_ark_bot_id = None   # Ark's Slack bot ID (e.g. "B08XXXXXXX")

# ---------------------------------------------------------------------------
# Bot-to-bot loop prevention
# ---------------------------------------------------------------------------
# Tracks exchanges per (thread, sender_bot_id) to cap runaway loops.
# Key: "thread_ts:bot_id" -> {"count": int, "last_ts": float}
_bot_exchange_tracker = defaultdict(lambda: {"count": 0, "last_ts": 0.0})
BOT_EXCHANGE_LIMIT = 4        # Max back-and-forth exchanges before suppressing
BOT_COOLDOWN_SECONDS = 300    # Reset counter after 5 minutes of silence


# ---------------------------------------------------------------------------
# Per-user rate limiting (protect against API cost abuse)
# ---------------------------------------------------------------------------
# Key: user_id -> list of timestamps (sliding window)
_user_rate_tracker: dict[str, list[float]] = {}
USER_RATE_LIMIT = 10           # Max messages per window
USER_RATE_WINDOW = 300         # 5-minute sliding window


def _check_user_rate_limit(user_id: str) -> bool:
    """Return True if the user is within rate limits, False if they should be throttled."""
    now = time.time()
    if user_id not in _user_rate_tracker:
        _user_rate_tracker[user_id] = []
    # Prune timestamps outside the window
    _user_rate_tracker[user_id] = [
        ts for ts in _user_rate_tracker[user_id] if now - ts < USER_RATE_WINDOW
    ]
    if len(_user_rate_tracker[user_id]) >= USER_RATE_LIMIT:
        return False
    _user_rate_tracker[user_id].append(now)
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_mention(text: str) -> str:
    """Remove @Ark mention from message text."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


# Allowed file extensions for uploads
_ALLOWED_EXTENSIONS = {".txt", ".csv", ".json", ".xlsx", ".xls", ".pdf", ".png",
                       ".jpg", ".jpeg", ".gif", ".md", ".py", ".html", ".css", ".js"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


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

        # Validate file extension
        ext = os.path.splitext(name)[1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            logger.warning(f"Rejected upload: {name} (extension {ext} not allowed)")
            continue

        # Validate file size (Slack provides this in metadata)
        file_size = f.get("size", 0)
        if file_size > _MAX_FILE_SIZE:
            logger.warning(f"Rejected upload: {name} ({file_size} bytes exceeds limit)")
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


def _ark_in_thread(channel: str, thread_ts: str) -> bool:
    """Check if Ark has previously responded in a thread."""
    from memory import ConversationMemory
    mem = ConversationMemory()
    return mem.has_assistant_messages(channel, thread_ts)


def _bot_loop_safe(event: dict) -> bool:
    """
    Returns True if it's safe to respond to this bot message.
    Returns False if we should suppress to prevent a loop.
    """
    thread_ts = event.get("thread_ts", event.get("ts", ""))
    sender_bot_id = event.get("bot_id", "")
    key = f"{thread_ts}:{sender_bot_id}"
    now = time.time()

    tracker = _bot_exchange_tracker[key]

    # Reset counter if enough time has passed (conversation cooled down)
    if now - tracker["last_ts"] > BOT_COOLDOWN_SECONDS:
        tracker["count"] = 0

    tracker["count"] += 1
    tracker["last_ts"] = now

    if tracker["count"] > BOT_EXCHANGE_LIMIT:
        logger.warning(
            f"Bot loop guard: {tracker['count']} exchanges with bot {sender_bot_id} "
            f"in thread {thread_ts}. Suppressing response."
        )
        return False

    return True


def _should_respond(event: dict) -> bool:
    """
    Decide whether Ark should respond to a channel message
    that was NOT an @mention. Returns True if Ark should engage.
    """
    # GATE 1: Skip message subtypes (edits, deletes, joins, etc.)
    if event.get("subtype"):
        return False

    # GATE 2: Skip our own messages (self-loop prevention)
    if _ark_bot_id and event.get("bot_id") == _ark_bot_id:
        return False
    if _ark_user_id and event.get("user") == _ark_user_id:
        return False

    # GATE 3: Skip @mentions (app_mention handler already covers those)
    text = event.get("text") or ""
    if _ark_user_id and f"<@{_ark_user_id}>" in text:
        return False

    # CHECK 1: "ark" mentioned by name (case-insensitive, word boundary)
    if re.search(r"\bark\b", text, re.IGNORECASE):
        logger.info("Auto-respond: 'ark' mentioned by name")
        return True

    # CHECK 2: Ark already participating in this thread
    thread_ts = event.get("thread_ts")
    if thread_ts and _ark_in_thread(event.get("channel", ""), thread_ts):
        # For bot senders, apply loop guard
        if event.get("bot_id"):
            if not _bot_loop_safe(event):
                return False
        logger.info(f"Auto-respond: Ark is participant in thread {thread_ts}")
        return True

    return False


# ---------------------------------------------------------------------------
# Core message handler
# ---------------------------------------------------------------------------

def _handle_message(event, say, client):
    """Core message handler - processes user message through Claude and responds."""
    from brain import think

    text = event.get("text", "")

    # Skip our own messages (belt-and-suspenders with _should_respond)
    if _ark_bot_id and event.get("bot_id") == _ark_bot_id:
        return
    if _ark_user_id and event.get("user") == _ark_user_id:
        return

    # Skip message subtypes (edits, deletes, etc.)
    if event.get("subtype"):
        return

    # Per-user rate limiting (skip for bots — they have the loop guard)
    sender = event.get("user", "")
    if sender and not event.get("bot_id"):
        if not _check_user_rate_limit(sender):
            thread_ts = event.get("thread_ts", event.get("ts", ""))
            say(text="You're sending messages too quickly. Please wait a moment and try again.",
                thread_ts=thread_ts)
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
    user_id = event.get("user", "unknown")

    # Resolve sender identity (handles both humans and bots)
    user_name = user_id
    is_bot_sender = bool(event.get("bot_id"))

    # Fallback bot detection: check subtype or user cache
    if not is_bot_sender:
        if event.get("subtype") == "bot_message":
            is_bot_sender = True
        else:
            try:
                from slack_users import is_bot_user
                if is_bot_user(client, user_id):
                    is_bot_sender = True
            except Exception:
                pass

    if is_bot_sender:
        bot_profile = event.get("bot_profile", {})
        user_name = bot_profile.get("name") or event.get("username") or user_id
        user_name = f"[BOT] {user_name}"

        # Auto-register bot in registry on first encounter
        try:
            from bot_registry import update_bot, _load
            registry = _load()
            bot_display = bot_profile.get("name") or event.get("username") or "UNKNOWN"
            key = bot_display.upper().replace(" ", "_")[:20]
            if key not in registry and key != "ARK":
                update_bot(key, {
                    "full_name": bot_display,
                    "platform": "slack",
                    "status": "active",
                    "notes": f"Auto-registered on first message. bot_id: {event.get('bot_id', 'N/A')}",
                    "interaction": {
                        "context": f"channel {channel}",
                        "summary": "First message detected - auto-registered",
                        "assessment": "New bot, needs observation",
                    },
                })
                logger.info(f"Auto-registered new bot: {key}")
        except Exception as e:
            logger.warning(f"Failed to auto-register bot: {e}")
    else:
        try:
            user_info = client.users_info(user=user_id)
            user_name = user_info["user"]["real_name"]
        except Exception:
            pass

    logger.info(f"Message from {user_name} in {channel}: {clean_text[:100]}...")

    # Build Slack context for tool execution (file uploads, etc.)
    slack_context = {
        "client": client,
        "channel": channel,
        "thread_ts": thread_ts,
        "user_id": user_id,
        "user_name": user_name,
        "timestamp": event["ts"],
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
        result = think(clean_text, channel, thread_ts, slack_context, user_name, user_id)

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

        logger.info(f"Replied to {user_name} ({len(result['text'])} chars)")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        say(
            text="Sorry, I hit an error processing your message. Please try again.",
            thread_ts=thread_ts,
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    global _ark_user_id, _ark_bot_id

    logger.info("Starting Ark...")

    app = App(
        token=os.environ["SLACK_BOT_TOKEN"].strip(),
        signing_secret=os.environ["SLACK_SIGNING_SECRET"].strip(),
    )

    # Cache Ark's own identity for self-detection and loop prevention
    try:
        auth = app.client.auth_test()
        _ark_user_id = auth["user_id"]
        _ark_bot_id = auth.get("bot_id")
        logger.info(f"Ark identity: user_id={_ark_user_id}, bot_id={_ark_bot_id}")
    except Exception as e:
        logger.error(f"Failed to get Ark identity: {e}")
        raise  # Cannot safely run without self-identification

    # Auto-discover workspace bots and sync to registry
    try:
        from slack_users import get_workspace_bots
        from bot_registry import sync_from_slack
        workspace_bots = get_workspace_bots(app.client)
        result = sync_from_slack(workspace_bots, ark_user_id=_ark_user_id)
        logger.info(f"Bot registry sync: {result}")
    except Exception as e:
        logger.warning(f"Bot registry sync failed (non-fatal): {e}")

    # Auto-sync tool definitions to Supabase tool_registry
    try:
        from tools import sync_tool_registry
        result = sync_tool_registry()
        logger.info(f"Tool registry sync: {result}")
    except Exception as e:
        logger.warning(f"Tool registry sync failed (non-fatal): {e}")

    @app.event("app_mention")
    def handle_mention(event, say, client):
        _handle_message(event, say, client)

    @app.event("message")
    def handle_message(event, say, client):
        # DMs - always respond
        if event.get("channel_type") == "im":
            _handle_message(event, say, client)
            return

        # Channel messages - respond if Ark should engage
        if _should_respond(event):
            _handle_message(event, say, client)

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"].strip())
    logger.info("Ark is online. Listening for messages and auto-responding when relevant.")
    handler.start()


if __name__ == "__main__":
    main()

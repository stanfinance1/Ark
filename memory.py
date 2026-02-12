"""
Ark - Conversation memory using SQLite.
Persists conversations across restarts so Ark remembers past interactions.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ark_memory.db")


class ConversationMemory:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_thread
                ON messages (channel, thread_ts)
            """)

    def save_message(self, channel: str, thread_ts: str, role: str, content):
        """Save a message to the conversation history."""
        # Content can be a string or a list of content blocks
        if not isinstance(content, str):
            content = json.dumps(content, default=str)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (channel, thread_ts, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (channel, thread_ts, role, content, datetime.now().isoformat()),
            )

    def get_history(self, channel: str, thread_ts: str, limit: int = 50) -> list:
        """Get conversation history for a thread, formatted for Claude API."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE channel = ? AND thread_ts = ? ORDER BY id DESC LIMIT ?",
                (channel, thread_ts, limit),
            ).fetchall()

        # Reverse to get chronological order
        rows.reverse()

        messages = []
        for role, content in rows:
            # Try to parse JSON content (for tool use blocks)
            try:
                parsed = json.loads(content)
                messages.append({"role": role, "content": parsed})
            except (json.JSONDecodeError, TypeError):
                messages.append({"role": role, "content": content})

        return messages

    def has_assistant_messages(self, channel: str, thread_ts: str) -> bool:
        """Check if Ark has responded in a thread (fast existence check)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM messages WHERE channel = ? AND thread_ts = ? AND role = 'assistant' LIMIT 1",
                (channel, thread_ts),
            ).fetchone()
        return row is not None

    def clear_thread(self, channel: str, thread_ts: str):
        """Clear conversation history for a thread."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM messages WHERE channel = ? AND thread_ts = ?",
                (channel, thread_ts),
            )

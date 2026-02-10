"""
Ark - Reminder system.
Database and utilities for scheduling and managing reminders.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import re

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ark_memory.db")


class ReminderManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create reminders table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_ts TEXT,
                    message TEXT NOT NULL,
                    cadence TEXT NOT NULL,
                    next_fire_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_fired_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fire_time
                ON reminders (next_fire_time, status)
            """)

    def create_reminder(
        self,
        user_id: str,
        user_name: str,
        channel: str,
        message: str,
        cadence: str,
        fire_time: datetime,
        thread_ts: Optional[str] = None,
    ) -> int:
        """Create a new reminder. Returns reminder ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO reminders
                (user_id, user_name, channel, thread_ts, message, cadence, next_fire_time, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    user_id,
                    user_name,
                    channel,
                    thread_ts,
                    message,
                    cadence,
                    fire_time.isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            return cursor.lastrowid

    def get_due_reminders(self) -> List[Dict]:
        """Get all reminders that are due to fire now."""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM reminders
                WHERE status = 'active' AND next_fire_time <= ?
                ORDER BY next_fire_time
                """,
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user_reminders(self, user_id: str) -> List[Dict]:
        """Get all active reminders for a user."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM reminders
                WHERE user_id = ? AND status = 'active'
                ORDER BY next_fire_time
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_reminder(self, reminder_id: int, user_id: str) -> bool:
        """Cancel a reminder. Returns True if successful."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND user_id = ?",
                (reminder_id, user_id),
            )
            return cursor.rowcount > 0

    def update_after_fire(self, reminder_id: int):
        """Update reminder after firing - mark as completed or calculate next fire time."""
        with sqlite3.connect(self.db_path) as conn:
            # Get current reminder
            row = conn.execute(
                "SELECT cadence, next_fire_time FROM reminders WHERE id = ?",
                (reminder_id,),
            ).fetchone()

            if not row:
                return

            cadence, next_fire_str = row
            current_fire = datetime.fromisoformat(next_fire_str)

            # If one-time, mark as completed
            if cadence == "once":
                conn.execute(
                    "UPDATE reminders SET status = 'completed', last_fired_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), reminder_id),
                )
                return

            # Calculate next fire time for recurring reminders
            next_fire = self._calculate_next_fire(cadence, current_fire)
            if next_fire:
                conn.execute(
                    "UPDATE reminders SET next_fire_time = ?, last_fired_at = ? WHERE id = ?",
                    (next_fire.isoformat(), datetime.now().isoformat(), reminder_id),
                )
            else:
                # If can't calculate next (shouldn't happen), mark completed
                conn.execute(
                    "UPDATE reminders SET status = 'completed', last_fired_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), reminder_id),
                )

    def _calculate_next_fire(self, cadence: str, current_fire: datetime) -> Optional[datetime]:
        """Calculate the next fire time based on cadence."""
        if cadence == "daily":
            return current_fire + timedelta(days=1)
        elif cadence.startswith("weekly_"):
            # weekly_monday, weekly_tuesday, etc.
            return current_fire + timedelta(weeks=1)
        elif cadence.startswith("monthly_"):
            # monthly_1, monthly_15, etc.
            # Add roughly 30 days, then adjust to correct day
            next_month = current_fire + timedelta(days=30)
            day_of_month = int(cadence.split("_")[1])
            try:
                # Try to set to the same day in next month
                return next_month.replace(day=day_of_month)
            except ValueError:
                # If day doesn't exist in that month, use last day
                next_month = next_month.replace(day=1) + timedelta(days=32)
                next_month = next_month.replace(day=1) - timedelta(days=1)
                return next_month
        return None


def parse_reminder_time(text: str) -> tuple[Optional[datetime], Optional[str]]:
    """
    Parse natural language time expressions into datetime and cadence type.
    Returns (fire_time, cadence) or (None, None) if can't parse.

    Supports:
    - "in 5 minutes", "in 2 hours", "in 3 days"
    - "at 3pm", "at 14:30", "tomorrow at 9am"
    - "daily at 9am", "every day at 10:30"
    - "every monday at 9am", "weekly on friday at 5pm"
    - "monthly on the 1st at 10am", "on the 15th of each month at 12pm"
    """
    text = text.lower().strip()
    now = datetime.now()

    # Pattern: "in X minutes/hours/days"
    match = re.search(r"in (\d+)\s+(minute|minutes|min|hour|hours|hr|day|days)", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if "min" in unit:
            fire_time = now + timedelta(minutes=amount)
        elif "hour" in unit or "hr" in unit:
            fire_time = now + timedelta(hours=amount)
        elif "day" in unit:
            fire_time = now + timedelta(days=amount)
        return fire_time, "once"

    # Daily patterns
    if "daily" in text or "every day" in text:
        time_match = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            ampm = time_match.group(3)

            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0

            fire_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if fire_time <= now:
                fire_time += timedelta(days=1)
            return fire_time, "daily"

    # Weekly patterns
    days_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }

    for day_name, day_num in days_map.items():
        if day_name in text and ("every" in text or "weekly" in text):
            time_match = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                ampm = time_match.group(3)

                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0

                # Calculate next occurrence of this weekday
                days_ahead = (day_num - now.weekday()) % 7
                if days_ahead == 0:
                    # Today is the day - check if time has passed
                    fire_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if fire_time <= now:
                        days_ahead = 7
                    else:
                        fire_time = now + timedelta(days=days_ahead)
                        fire_time = fire_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                else:
                    fire_time = now + timedelta(days=days_ahead)
                    fire_time = fire_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

                return fire_time, f"weekly_{day_name}"

    # Monthly patterns
    monthly_match = re.search(r"(?:monthly|each month|every month).*?(?:on the |the )?(\d{1,2})(?:st|nd|rd|th)?", text)
    if monthly_match:
        day_of_month = int(monthly_match.group(1))
        time_match = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)

        hour, minute = 9, 0  # Default to 9am if no time specified
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            ampm = time_match.group(3)

            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0

        # Calculate next occurrence of this day
        try:
            fire_time = now.replace(day=day_of_month, hour=hour, minute=minute, second=0, microsecond=0)
            if fire_time <= now:
                # Move to next month
                if now.month == 12:
                    fire_time = fire_time.replace(year=now.year + 1, month=1)
                else:
                    fire_time = fire_time.replace(month=now.month + 1)
        except ValueError:
            # Day doesn't exist in current month, try next month
            if now.month == 12:
                fire_time = datetime(now.year + 1, 1, day_of_month, hour, minute)
            else:
                fire_time = datetime(now.year, now.month + 1, day_of_month, hour, minute)

        return fire_time, f"monthly_{day_of_month}"

    # Simple time today/tomorrow patterns
    time_match = re.search(r"(today|tomorrow)?\s*at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if time_match:
        day_offset = 1 if time_match.group(1) == "tomorrow" else 0
        hour = int(time_match.group(2))
        minute = int(time_match.group(3) or 0)
        ampm = time_match.group(4)

        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

        fire_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_offset == 0 and fire_time <= now:
            fire_time += timedelta(days=1)
        else:
            fire_time += timedelta(days=day_offset)

        return fire_time, "once"

    return None, None

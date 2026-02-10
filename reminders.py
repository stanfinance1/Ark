"""
Ark - Reminder system (IMPROVED VERSION).
Database and utilities for scheduling and managing reminders.

Improvements:
- Fixed monthly calculation bug (proper month arithmetic)
- Extracted duplicate AM/PM parsing logic to helper
- Simplified weekly calculation logic
- Added input validation
- Better error handling
- Single consistent 'now' timestamp
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import re
import calendar
from zoneinfo import ZoneInfo

# User timezone - all reminder times are parsed and displayed in this timezone
USER_TIMEZONE = ZoneInfo("America/Los_Angeles")  # Pacific Time

# Timezone mappings for common abbreviations
TIMEZONE_MAP = {
    # Pacific
    "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "pacific": "America/Los_Angeles",
    # Mountain
    "mt": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "mountain": "America/Denver",
    # Central
    "ct": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "central": "America/Chicago",
    # Eastern
    "et": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "eastern": "America/New_York",
    # UTC
    "utc": "UTC",
    "gmt": "UTC",
}

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
                    datetime.now(USER_TIMEZONE).isoformat(),
                ),
            )
            return cursor.lastrowid

    def get_due_reminders(self) -> List[Dict]:
        """Get all reminders that are due to fire now."""
        now = datetime.now(USER_TIMEZONE).isoformat()
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
                    (datetime.now(USER_TIMEZONE).isoformat(), reminder_id),
                )
                return

            # Calculate next fire time for recurring reminders
            next_fire = self._calculate_next_fire(cadence, current_fire)
            if next_fire:
                conn.execute(
                    "UPDATE reminders SET next_fire_time = ?, last_fired_at = ? WHERE id = ?",
                    (next_fire.isoformat(), datetime.now(USER_TIMEZONE).isoformat(), reminder_id),
                )
            else:
                # If can't calculate next (shouldn't happen), mark completed
                conn.execute(
                    "UPDATE reminders SET status = 'completed', last_fired_at = ? WHERE id = ?",
                    (datetime.now(USER_TIMEZONE).isoformat(), reminder_id),
                )

    def _calculate_next_fire(self, cadence: str, current_fire: datetime) -> Optional[datetime]:
        """Calculate the next fire time based on cadence."""
        if cadence == "daily":
            return current_fire + timedelta(days=1)
        elif cadence.startswith("weekly_"):
            return current_fire + timedelta(weeks=1)
        elif cadence.startswith("monthly_"):
            # IMPROVED: Proper month arithmetic
            day_of_month = int(cadence.split("_")[1])
            year = current_fire.year
            month = current_fire.month + 1

            # Handle year rollover
            if month > 12:
                month = 1
                year += 1

            # Handle day overflow (e.g., Jan 31 -> Feb 31 doesn't exist)
            max_day = calendar.monthrange(year, month)[1]
            day = min(day_of_month, max_day)

            return current_fire.replace(year=year, month=month, day=day)
        return None


def _parse_time(hour: int, minute: int, ampm: Optional[str]) -> Tuple[int, int]:
    """
    Helper to convert 12-hour time with AM/PM to 24-hour format.
    Returns (hour_24, minute).
    """
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def _extract_timezone(text: str) -> Tuple[str, Optional[ZoneInfo]]:
    """
    Extract timezone from text if present.
    Returns (text_without_tz, timezone) or (original_text, None).
    """
    text_lower = text.lower()

    # Check for timezone abbreviations at the end of common time patterns
    # e.g. "at 3pm ET", "tomorrow at 5pm EST", "daily at 9am Pacific"
    for tz_abbr, tz_name in TIMEZONE_MAP.items():
        # Pattern: time expression followed by timezone
        pattern = r'\b' + re.escape(tz_abbr) + r'\b'
        if re.search(pattern, text_lower):
            # Remove the timezone from text
            cleaned_text = re.sub(pattern, '', text_lower).strip()
            return cleaned_text, ZoneInfo(tz_name)

    return text, None


def parse_reminder_time(text: str) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parse natural language time expressions into datetime and cadence type.
    Returns (fire_time, cadence) or (None, None) if can't parse.

    Supports:
    - "in 5 minutes", "in 2 hours", "in 3 days"
    - "at 3pm", "at 14:30", "tomorrow at 9am"
    - "daily at 9am", "every day at 10:30"
    - "every monday at 9am", "weekly on friday at 5pm"
    - "monthly on the 1st at 10am", "on the 15th of each month at 12pm"
    - Timezone support: "at 5pm ET", "tomorrow at 3pm EST", "daily at 9am Pacific"

    If no timezone is specified, defaults to USER_TIMEZONE (Pacific Time).
    All times are converted to Pacific Time for storage.
    """
    text = text.lower().strip()

    # Extract timezone from text if present
    text_clean, input_timezone = _extract_timezone(text)
    if input_timezone is None:
        input_timezone = USER_TIMEZONE

    # Use input timezone for parsing, but get "now" in that timezone
    now = datetime.now(input_timezone)

    # Pattern: "in X minutes/hours/days"
    match = re.search(r"in (\d+)\s+(minute|minutes|min|hour|hours|hr|day|days)", text_clean)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if "min" in unit:
            fire_time = now + timedelta(minutes=amount)
        elif "hour" in unit or "hr" in unit:
            fire_time = now + timedelta(hours=amount)
        elif "day" in unit:
            fire_time = now + timedelta(days=amount)
        # Convert to Pacific Time if parsed in different timezone
        if input_timezone != USER_TIMEZONE:
            fire_time = fire_time.astimezone(USER_TIMEZONE)
        return fire_time, "once"

    # Daily patterns
    if "daily" in text_clean or "every day" in text_clean:
        time_match = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_clean)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            ampm = time_match.group(3)
            hour, minute = _parse_time(hour, minute, ampm)

            fire_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if fire_time <= now:
                fire_time += timedelta(days=1)
            # Convert to Pacific Time if parsed in different timezone
            if input_timezone != USER_TIMEZONE:
                fire_time = fire_time.astimezone(USER_TIMEZONE)
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
        if day_name in text_clean and ("every" in text_clean or "weekly" in text_clean):
            time_match = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_clean)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                ampm = time_match.group(3)
                hour, minute = _parse_time(hour, minute, ampm)

                # IMPROVED: Simpler weekly calculation
                days_ahead = (day_num - now.weekday()) % 7
                fire_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # If it's today but time has passed, schedule for next week
                if days_ahead == 0 and fire_time <= now:
                    days_ahead = 7

                fire_time = now + timedelta(days=days_ahead)
                fire_time = fire_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # Convert to Pacific Time if parsed in different timezone
                if input_timezone != USER_TIMEZONE:
                    fire_time = fire_time.astimezone(USER_TIMEZONE)

                return fire_time, f"weekly_{day_name}"

    # Monthly patterns
    monthly_match = re.search(r"(?:monthly|each month|every month).*?(?:on the |the )?(\d{1,2})(?:st|nd|rd|th)?", text_clean)
    if monthly_match:
        day_of_month = int(monthly_match.group(1))

        # IMPROVED: Validate day
        if day_of_month < 1 or day_of_month > 31:
            return None, None

        time_match = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_clean)
        hour, minute = 9, 0  # Default to 9am if no time specified
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            ampm = time_match.group(3)
            hour, minute = _parse_time(hour, minute, ampm)

        # Calculate next occurrence of this day
        try:
            fire_time = now.replace(day=day_of_month, hour=hour, minute=minute, second=0, microsecond=0)
            if fire_time <= now:
                # Move to next month
                month = now.month + 1
                year = now.year
                if month > 12:
                    month = 1
                    year += 1

                # Handle day overflow
                max_day = calendar.monthrange(year, month)[1]
                day = min(day_of_month, max_day)
                fire_time = fire_time.replace(year=year, month=month, day=day)
        except ValueError:
            # Day doesn't exist in current month, try next month
            month = now.month + 1
            year = now.year
            if month > 12:
                month = 1
                year += 1

            max_day = calendar.monthrange(year, month)[1]
            day = min(day_of_month, max_day)
            fire_time = datetime(year, month, day, hour, minute, tzinfo=input_timezone)

        # Convert to Pacific Time if parsed in different timezone
        if input_timezone != USER_TIMEZONE:
            fire_time = fire_time.astimezone(USER_TIMEZONE)

        return fire_time, f"monthly_{day_of_month}"

    # Simple time today/tomorrow patterns
    time_match = re.search(r"(today|tomorrow)?\s*at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_clean)
    if time_match:
        day_offset = 1 if time_match.group(1) == "tomorrow" else 0
        hour = int(time_match.group(2))
        minute = int(time_match.group(3) or 0)
        ampm = time_match.group(4)
        hour, minute = _parse_time(hour, minute, ampm)

        fire_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_offset == 0 and fire_time <= now:
            fire_time += timedelta(days=1)
        else:
            fire_time += timedelta(days=day_offset)

        # Convert to Pacific Time if parsed in different timezone
        if input_timezone != USER_TIMEZONE:
            fire_time = fire_time.astimezone(USER_TIMEZONE)

        return fire_time, "once"

    return None, None

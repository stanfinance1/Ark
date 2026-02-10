# Ark Reminder System

## Overview

Ark now supports scheduling reminders with flexible cadences. Reminders are sent as Slack messages with @mentions in the same channel/thread where they were created.

## Features

- **One-time reminders**: "in 5 minutes", "tomorrow at 3pm", "at 5:30pm"
- **Daily reminders**: "daily at 9am", "every day at 10:30"
- **Weekly reminders**: "every Monday at 10am", "weekly on Friday at 5pm"
- **Monthly reminders**: "monthly on the 15th at 2pm", "on the 1st of each month at 9am"
- **List active reminders**: See all scheduled reminders with IDs
- **Cancel reminders**: Cancel by ID

## Usage Examples

**Create a reminder:**
```
@Ark remind me to review metrics tomorrow at 9am
@Ark set a reminder to check inventory in 30 minutes
@Ark remind me every Monday at 10am to send weekly report
```

**List reminders:**
```
@Ark show my reminders
@Ark what reminders do I have?
```

**Cancel a reminder:**
```
@Ark cancel reminder 5
@Ark delete reminder 3
```

## Architecture

### Components

1. **Database** (`ark_memory.db` - `reminders` table)
   - Stores user, channel, message, cadence, next fire time
   - SQLite for persistence across restarts

2. **Tools** (`tools.py`)
   - `create_reminder` - Parse natural language and create reminder
   - `list_reminders` - Show user's active reminders
   - `cancel_reminder` - Cancel by ID

3. **Parser** (`reminders.py` - `parse_reminder_time()`)
   - Handles natural language time expressions
   - Returns `(datetime, cadence)` tuple
   - Supports relative times ("in X"), absolute times ("at Y"), and recurring patterns

4. **Scheduler** (`scheduler.py`)
   - Background process running every 30 seconds
   - Checks for due reminders (`next_fire_time <= now`)
   - Sends Slack message with @mention
   - Updates recurring reminders with next fire time
   - Marks one-time reminders as completed

5. **Launcher** (`launcher.py`)
   - Starts both bot and scheduler as separate processes
   - Railway runs this via `Procfile`

## Deployment

The system deploys to Railway automatically via git push:

1. **Local testing:**
   ```bash
   cd claude-only/ark
   python test_reminders.py  # Test parsing and DB
   ```

2. **Deploy to Railway:**
   ```bash
   git add .
   git commit -m "Add reminder system"
   git push origin main
   ```

3. **Railway auto-deploys** (~30 seconds)
   - Runs `launcher.py` which starts bot + scheduler
   - Both processes run 24/7
   - Scheduler checks every 30 seconds for due reminders

## Files Added

- `reminders.py` - Database manager and time parser
- `scheduler.py` - Background scheduler process
- `launcher.py` - Multi-process launcher
- `test_reminders.py` - Test suite
- Updated: `tools.py`, `brain.py`, `config.py`, `Procfile`

## Database Schema

```sql
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,           -- Slack user ID
    user_name TEXT NOT NULL,         -- Display name
    channel TEXT NOT NULL,           -- Channel to send reminder
    thread_ts TEXT,                  -- Thread timestamp (optional)
    message TEXT NOT NULL,           -- Reminder message
    cadence TEXT NOT NULL,           -- once, daily, weekly_*, monthly_*
    next_fire_time TEXT NOT NULL,   -- ISO datetime
    status TEXT DEFAULT 'active',   -- active, completed, cancelled
    created_at TEXT NOT NULL,        -- ISO datetime
    last_fired_at TEXT               -- ISO datetime
);
```

## Cadence Types

- `once` - One-time reminder
- `daily` - Every day at same time
- `weekly_monday`, `weekly_tuesday`, etc. - Every X day at same time
- `monthly_1`, `monthly_15`, etc. - Every month on day N

## Testing Locally

1. Set up Slack bot tokens in `.env`
2. Run bot: `python launcher.py`
3. Send test messages in Slack
4. Check scheduler logs for reminder firing

## Notes

- Reminders fire with 30-second precision (scheduler check interval)
- User isolation: Users only see/cancel their own reminders
- Thread-aware: Reminders in threads stay in threads
- Mentions ensure notifications reach users on mobile/desktop

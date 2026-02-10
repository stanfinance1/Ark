"""Test script to verify timezone-aware reminder system."""

import sys
import os
from datetime import datetime

# Add ark directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reminders import parse_reminder_time, USER_TIMEZONE

def test_parse_reminder_time():
    """Test that reminder times are parsed in Pacific Time."""

    # Get current time in PST
    now = datetime.now(USER_TIMEZONE)
    print(f"Current time in Pacific: {now.strftime('%Y-%m-%d %I:%M %p %Z')}")
    print()

    # Test cases
    test_cases = [
        "at 10:14 PM",
        "tomorrow at 3pm",
        "in 30 minutes",
        "daily at 9am",
        "every Monday at 10am",
    ]

    for test in test_cases:
        fire_time, cadence = parse_reminder_time(test)
        if fire_time:
            tz_name = fire_time.strftime("%Z")  # PST or PDT
            print(f"Input: '{test}'")
            print(f"  -> {fire_time.strftime('%Y-%m-%d at %I:%M %p')} {tz_name}")
            print(f"  -> Cadence: {cadence}")
            print(f"  -> ISO format: {fire_time.isoformat()}")
            print()
        else:
            print(f"Input: '{test}' -> FAILED TO PARSE")
            print()

if __name__ == "__main__":
    test_parse_reminder_time()

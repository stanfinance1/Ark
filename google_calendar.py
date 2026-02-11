"""
Ark - Google Calendar integration.
Creates events with Google Meet links using a service account.
"""

import os
import json
import base64
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

USER_TIMEZONE = ZoneInfo("America/Los_Angeles")
TIMEZONE_STRING = "America/Los_Angeles"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Module-level service cache
_service = None


def _get_service():
    """Get or create the Google Calendar API service."""
    global _service
    if _service:
        return _service

    creds_b64 = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS", "").strip()
    if not creds_b64:
        raise ValueError("GOOGLE_CALENDAR_CREDENTIALS environment variable not set")

    creds_json = json.loads(base64.b64decode(creds_b64))
    credentials = Credentials.from_service_account_info(creds_json, scopes=SCOPES)

    _service = build("calendar", "v3", credentials=credentials)
    logger.info("Google Calendar service initialized")
    return _service


def create_event(
    summary,
    start_time,
    duration_minutes=30,
    description="",
    attendee_emails=None,
    add_meet_link=True,
):
    """
    Create a Google Calendar event.

    Args:
        summary: Event title
        start_time: datetime object for event start
        duration_minutes: Duration in minutes (default 30)
        description: Optional event description/agenda
        attendee_emails: List of attendee email addresses
        add_meet_link: Whether to create a Google Meet link (default True)

    Returns dict with: event_id, html_link, meet_link, start, end, attendees
    """
    service = _get_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary").strip()
    owner_email = os.environ.get("OWNER_EMAIL", "").strip()

    end_time = start_time + timedelta(minutes=duration_minutes)

    event_body = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": TIMEZONE_STRING,
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": TIMEZONE_STRING,
        },
    }

    # Add attendees (owner always included)
    attendees = []
    if owner_email:
        attendees.append({"email": owner_email})
    if attendee_emails:
        for email in attendee_emails:
            email = email.strip()
            if email and email != owner_email:
                attendees.append({"email": email})
    if attendees:
        event_body["attendees"] = attendees

    # Add Google Meet conferencing
    if add_meet_link:
        event_body["conferenceData"] = {
            "createRequest": {
                "requestId": f"ark-{start_time.timestamp():.0f}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    event = service.events().insert(
        calendarId=calendar_id,
        body=event_body,
        conferenceDataVersion=1 if add_meet_link else 0,
        sendUpdates="all",
    ).execute()

    # Extract Meet link
    meet_link = ""
    if event.get("conferenceData", {}).get("entryPoints"):
        for ep in event["conferenceData"]["entryPoints"]:
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break

    return {
        "event_id": event.get("id", ""),
        "html_link": event.get("htmlLink", ""),
        "meet_link": meet_link,
        "start": start_time.strftime("%Y-%m-%d %I:%M %p"),
        "end": end_time.strftime("%I:%M %p"),
        "attendees": [a["email"] for a in attendees],
    }

"""
Ark - Gmail integration.
Send and search emails using OAuth2 user credentials (stan@hnyplus.com).

Uses the same OAuth refresh_token flow as Claude Code's direct API access.
Env vars required on Railway:
  GMAIL_CLIENT_ID       - OAuth client ID
  GMAIL_CLIENT_SECRET   - OAuth client secret
  GMAIL_REFRESH_TOKEN   - OAuth refresh token (long-lived)
"""

import os
import base64
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SENDER_EMAIL = "stan@hnyplus.com"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]

# Module-level service cache
_service = None


def _get_service():
    """Get or create the Gmail API service."""
    global _service
    if _service:
        return _service

    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(
            "Gmail not configured. Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, "
            "and GMAIL_REFRESH_TOKEN environment variables."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )

    _service = build("gmail", "v1", credentials=creds)
    logger.info("Gmail service initialized")
    return _service


def send_email(to, subject, body, html_body=None):
    """
    Send an email from stan@hnyplus.com.

    Args:
        to: Recipient email address (or comma-separated list)
        subject: Email subject line
        body: Plain text body
        html_body: Optional HTML body (sends as multipart if provided)

    Returns dict with: message_id, to, subject
    """
    service = _get_service()

    if html_body:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    else:
        msg = MIMEText(body)

    msg["to"] = to
    msg["from"] = SENDER_EMAIL
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()

    logger.info(f"Email sent to {to}: {subject} (id: {sent.get('id')})")

    return {
        "message_id": sent.get("id", ""),
        "to": to,
        "subject": subject,
    }


def search_emails(query, max_results=5):
    """
    Search emails in stan@hnyplus.com inbox.

    Args:
        query: Gmail search query (e.g. "from:liam@hnyplus.com", "subject:invoice")
        max_results: Max emails to return (default 5)

    Returns list of dicts with: message_id, from, to, subject, date, snippet
    """
    service = _get_service()

    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        return []

    emails = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        emails.append({
            "message_id": m["id"],
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
        })

    return emails

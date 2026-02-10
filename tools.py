"""
Ark - Tool definitions and execution.
"""

import subprocess
import os
import sys
import tempfile
import logging
import concurrent.futures

import requests
import trafilatura
from bs4 import BeautifulSoup
from ddgs import DDGS

from config import BASE_DIR, TMP_DIR

logger = logging.getLogger(__name__)
PYTHON = sys.executable
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ---------------------------------------------------------------------------
# Tool definitions (Claude API format)
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS = [
    {
        "name": "run_python",
        "description": "Execute Python code on the server. Has access to pandas, openpyxl, numpy, matplotlib, and all standard libraries. Use this for data analysis, calculations, chart generation, file processing, etc. Print output to stdout for it to be returned. Save generated files (charts, spreadsheets) to the tmp directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use print() for text output. Save files to the tmp directory path provided in the TMP_DIR variable.",
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of what this code does (for logging).",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a text file (CSV, TXT, JSON, Python, etc.). For Excel files, use run_python with pandas instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to read.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to read. Defaults to 200.",
                    "default": 200,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and directories at a given path. Use this to explore the project structure, find input data files, or check what outputs exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list. Defaults to the project root.",
                    "default": "",
                },
            },
        },
    },
    {
        "name": "upload_file",
        "description": "Upload a file to the current Slack channel. Use this after generating charts, spreadsheets, or reports to share them directly in the conversation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to upload.",
                },
                "title": {
                    "type": "string",
                    "description": "Title/caption for the uploaded file.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the internet using DuckDuckGo. Returns top results with titles, URLs, and snippets. Good for quick lookups: weather, stock prices, simple facts. For in-depth research, use web_research instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'NYC weather today', 'AAPL stock price').",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return. Defaults to 5.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch a web page and extract its main text content cleanly. Use this to read a specific URL (article, documentation, blog post). Returns clean article text, not raw HTML.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch (e.g. 'https://example.com/article').",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters of text to return. Defaults to 5000.",
                    "default": 5000,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_research",
        "description": "All-in-one web research tool. Searches the web AND automatically reads the top results in a single call. Returns search results with full article content extracted from the best pages. Use this for any research question - it's faster than calling web_search + fetch_url separately. One call does it all.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research question or search query (e.g. 'DTC subscription brands with $50 AOV benchmarks').",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of search results to return. Defaults to 5.",
                    "default": 5,
                },
                "fetch_top": {
                    "type": "integer",
                    "description": "Number of top results to auto-fetch full content from. Defaults to 2.",
                    "default": 2,
                },
                "max_chars_per_page": {
                    "type": "integer",
                    "description": "Max characters to extract per page. Defaults to 3000.",
                    "default": 3000,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_reminder",
        "description": "Schedule a reminder to be sent at a specific time or on a recurring schedule. The reminder will be posted in the same channel where it was created, with an @mention to notify you. All times are in Pacific Time (US/Pacific). Supports one-time reminders (e.g. 'in 5 minutes', 'tomorrow at 3pm'), daily reminders (e.g. 'daily at 9am'), weekly reminders (e.g. 'every Monday at 10am'), and monthly reminders (e.g. 'monthly on the 15th at 2pm').",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The reminder message to send (e.g. 'Review weekly metrics', 'Follow up with supplier').",
                },
                "when": {
                    "type": "string",
                    "description": "Natural language description of when to send the reminder in Pacific Time. Examples: 'in 30 minutes', 'tomorrow at 3pm', 'daily at 9am', 'every Monday at 10am', 'monthly on the 1st at 9am'.",
                },
            },
            "required": ["message", "when"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List all active reminders for the current user. Shows reminder ID, message, next fire time in Pacific Time, and cadence (one-time, daily, weekly, monthly).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel an active reminder by its ID. Use list_reminders first to see all active reminders and their IDs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "integer",
                    "description": "The ID of the reminder to cancel (get this from list_reminders).",
                },
            },
            "required": ["reminder_id"],
        },
    },
]

# ---------------------------------------------------------------------------
# Shared helpers (no duplication)
# ---------------------------------------------------------------------------

def _download_page(url: str, timeout: int = 15) -> str:
    """Download HTML from a URL. Trafilatura first, requests fallback."""
    html = trafilatura.fetch_url(url)
    if html:
        return html
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
    resp.raise_for_status()
    return resp.text


def _extract_text(html: str, max_chars: int = 10000) -> str:
    """Extract readable text from HTML. Trafilatura first, BS4 fallback."""
    text = trafilatura.extract(
        html, include_links=True, include_tables=True, favor_recall=True,
    )
    if not text:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    if not text:
        return ""
    return text[:max_chars] + "\n\n... (truncated)" if len(text) > max_chars else text


def _ddg_search(query: str, max_results: int = 5) -> list:
    """Run a DuckDuckGo search. Returns list of {title, href, body}."""
    return list(DDGS().text(query, max_results=max_results))


def _format_results(results: list, bold: bool = False) -> str:
    """Format DDG results into readable text."""
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        lines.append(f"{i}. {'**' + title + '**' if bold else title}")
        lines.append(f"   URL: {r.get('href', '')}")
        lines.append(f"   {r.get('body', '')}")
        lines.append("")
    return "\n".join(lines).strip()


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def execute_tool(name: str, inputs: dict, slack_context: dict = None) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if name == "run_python":
            return _run_python(inputs.get("code", ""), inputs.get("description", ""))
        elif name == "read_file":
            return _read_file(inputs.get("path", ""), inputs.get("max_lines", 200))
        elif name == "list_files":
            return _list_files(inputs.get("path", ""))
        elif name == "upload_file":
            return _upload_file(inputs.get("path", ""), inputs.get("title", ""), slack_context)
        elif name == "web_search":
            return _web_search(inputs.get("query", ""), inputs.get("max_results", 5))
        elif name == "fetch_url":
            return _fetch_url(inputs.get("url", ""), inputs.get("max_chars", 5000))
        elif name == "web_research":
            return _web_research(
                inputs.get("query", ""),
                inputs.get("num_results", 5),
                inputs.get("fetch_top", 2),
                inputs.get("max_chars_per_page", 3000),
            )
        elif name == "create_reminder":
            return _create_reminder(inputs.get("message", ""), inputs.get("when", ""), slack_context)
        elif name == "list_reminders":
            return _list_reminders(slack_context)
        elif name == "cancel_reminder":
            return _cancel_reminder(inputs.get("reminder_id"), slack_context)
        else:
            return f"Error: Unknown tool '{name}'"
    except Exception as e:
        return f"Error executing {name}: {e}"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _run_python(code: str, description: str = "") -> str:
    """Execute Python code in a subprocess and return stdout + stderr."""
    full_code = f"import sys, os\nTMP_DIR = r\"{TMP_DIR}\"\nBASE_DIR = r\"{BASE_DIR}\"\nos.makedirs(TMP_DIR, exist_ok=True)\n\n{code}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", dir=TMP_DIR, delete=False) as f:
        f.write(full_code)
        script_path = f.name

    try:
        result = subprocess.run(
            [PYTHON, script_path],
            capture_output=True, text=True, timeout=120, cwd=BASE_DIR,
        )
        output = result.stdout or ""
        if result.stderr:
            output += "\n[STDERR]\n" + result.stderr
        if result.returncode != 0:
            output += f"\n[Exit code: {result.returncode}]"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Script timed out after 120 seconds."
    finally:
        os.unlink(script_path)


def _read_file(path: str, max_lines: int = 200) -> str:
    """Read a text file and return its contents."""
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    if not os.path.exists(path):
        return f"Error: File not found: {path}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"\n... (truncated at {max_lines} lines)")
                    break
                lines.append(line)
        return "".join(lines)
    except Exception as e:
        return f"Error reading file: {e}"


def _list_files(path: str = "") -> str:
    """List files in a directory."""
    if not path:
        path = BASE_DIR
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    if not os.path.isdir(path):
        return f"Error: Not a directory: {path}"
    try:
        entries = []
        for entry in sorted(os.listdir(path)):
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                entries.append(f"  {entry}/")
            else:
                entries.append(f"  {entry} ({_human_size(os.path.getsize(full))})")
        return f"Contents of {path}:\n" + "\n".join(entries)
    except Exception as e:
        return f"Error listing directory: {e}"


def _upload_file(path: str, title: str, slack_context: dict) -> str:
    """Upload a file to Slack."""
    if not slack_context:
        return "Error: No Slack context available for file upload."
    if not os.path.exists(path):
        return f"Error: File not found: {path}"
    client = slack_context.get("client")
    channel = slack_context.get("channel")
    if not client or not channel:
        return "Error: Missing Slack client or channel."
    try:
        client.files_upload_v2(
            channel=channel, file=path,
            title=title or os.path.basename(path),
            thread_ts=slack_context.get("thread_ts"),
        )
        return f"Uploaded {os.path.basename(path)} to Slack."
    except Exception as e:
        return f"Error uploading file: {e}"


def _web_search(query: str, max_results: int = 5) -> str:
    """Quick web search - returns titles, URLs, and snippets."""
    if not query:
        return "Error: No search query provided."
    try:
        results = _ddg_search(query, max_results)
        return _format_results(results) if results else f"No results found for: {query}"
    except Exception as e:
        return f"Error searching web: {e}"


def _fetch_url(url: str, max_chars: int = 5000) -> str:
    """Fetch a single URL and extract clean text."""
    if not url:
        return "Error: No URL provided."
    try:
        html = _download_page(url)
        return _extract_text(html, max_chars) or "(page had no extractable text content)"
    except Exception as e:
        return f"Error fetching URL: {e}"


def _web_research(query: str, num_results: int = 5, fetch_top: int = 2, max_chars_per_page: int = 3000) -> str:
    """All-in-one: search + auto-fetch top results in parallel."""
    if not query:
        return "Error: No query provided."
    try:
        results = _ddg_search(query, num_results)
    except Exception as e:
        return f"Error searching: {e}"
    if not results:
        return f"No results found for: {query}"

    output = [f"## Search Results for: {query}\n", _format_results(results, bold=True)]

    # Pick fetchable URLs (skip video/forum/PDF)
    skip = ("youtube.com", "reddit.com/r/", ".pdf")
    urls = [
        (r.get("title", ""), r["href"])
        for r in results[:fetch_top]
        if r.get("href") and not any(s in r["href"] for s in skip)
    ]

    if urls:
        output.append("\n---\n## Full Content from Top Results\n")

        def _fetch_one(title_url):
            title, url = title_url
            try:
                html = _download_page(url, timeout=10)
                text = _extract_text(html, max_chars_per_page)
                return title, url, text
            except Exception as e:
                return title, url, f"(failed to fetch: {e})"

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for title, url, text in pool.map(_fetch_one, urls):
                if text:
                    output.extend([f"### {title}", f"Source: {url}\n", text, "\n---\n"])

    return "\n".join(output).strip()


def _create_reminder(message: str, when: str, slack_context: dict) -> str:
    """Create a new reminder."""
    import random
    from reminders import ReminderManager, parse_reminder_time

    if not message or not when:
        return "Error: Both 'message' and 'when' are required."

    if not slack_context:
        return "Error: No Slack context available."

    # Parse the time expression
    fire_time, cadence = parse_reminder_time(when)
    if not fire_time or not cadence:
        return f"Error: Could not parse time expression '{when}'. Try something like: 'in 30 minutes', 'tomorrow at 3pm', 'daily at 9am', 'every Monday at 10am', or 'monthly on the 15th at 2pm'."

    # Get user info from context
    user_id = slack_context.get("user_id", "unknown")
    user_name = slack_context.get("user_name", "unknown")
    channel = slack_context.get("channel")
    thread_ts = slack_context.get("thread_ts")

    # Create the reminder
    manager = ReminderManager()
    reminder_id = manager.create_reminder(
        user_id=user_id,
        user_name=user_name,
        channel=channel,
        message=message,
        cadence=cadence,
        fire_time=fire_time,
        thread_ts=thread_ts,
    )

    # Format response based on cadence
    cadence_display = {
        "once": "one-time",
        "daily": "daily",
    }
    if cadence.startswith("weekly_"):
        day = cadence.split("_")[1].capitalize()
        cadence_display[cadence] = f"weekly (every {day})"
    elif cadence.startswith("monthly_"):
        day_num = cadence.split("_")[1]
        cadence_display[cadence] = f"monthly (on the {day_num})"

    cadence_text = cadence_display.get(cadence, cadence)

    # Nautical quotes from classic sea adventure literature
    nautical_quotes = [
        "\"The sea finds out everything you did wrong.\" - Francis Stokes",
        "\"Twenty years from now you will be more disappointed by the things you didn't do than by the ones you did do.\" - Mark Twain",
        "\"I must go down to the seas again, to the lonely sea and the sky.\" - John Masefield",
        "\"The cure for anything is salt water: sweat, tears, or the sea.\" - Isak Dinesen",
        "\"It is not the ship so much as the skillful sailing that assures the prosperous voyage.\" - George William Curtis",
        "\"A smooth sea never made a skilled sailor.\" - Franklin D. Roosevelt",
        "\"The sea does not reward those who are too anxious, too greedy, or too impatient.\" - Anne Morrow Lindbergh",
        "\"We must free ourselves of the hope that the sea will ever rest. We must learn to sail in high winds.\" - Aristotle Onassis",
        "\"The voice of the sea speaks to the soul.\" - Kate Chopin",
        "\"He that will not sail till all dangers are over must never put to sea.\" - Thomas Fuller",
        "\"There is nothing more enticing, disenchanting, and enslaving than the life at sea.\" - Joseph Conrad",
        "\"The sea, once it casts its spell, holds one in its net of wonder forever.\" - Jacques Cousteau",
        "\"In the waves of change we find our true direction.\" - Unknown",
        "\"You can't stop the waves, but you can learn to surf.\" - Jon Kabat-Zinn",
        "\"The pessimist complains about the wind; the optimist expects it to change; the realist adjusts the sails.\" - William Arthur Ward",
        "\"A ship in harbor is safe, but that is not what ships are built for.\" - John A. Shedd",
        "\"To reach a port we must set sail.\" - Franklin D. Roosevelt",
        "\"There are good ships and there are wood ships, but the best ships are friendships.\" - Irish Proverb",
        "\"The sea is the same as it has been since before men ever went on it in boats.\" - Ernest Hemingway",
        "\"For whatever we lose, it's always ourselves we find in the sea.\" - E.E. Cummings",
    ]

    quote = random.choice(nautical_quotes)

    # Get timezone name for display
    tz_name = fire_time.strftime("%Z")  # PST or PDT

    return f"Reminder created (ID: {reminder_id})\n\nMessage: {message}\nFirst reminder: {fire_time.strftime('%Y-%m-%d at %I:%M %p')} {tz_name}\nCadence: {cadence_text}\n\nI'll send a message in this {'thread' if thread_ts else 'channel'} and @mention you when it's time.\n\n{quote}"


def _list_reminders(slack_context: dict) -> str:
    """List all active reminders for the user."""
    from reminders import ReminderManager, USER_TIMEZONE
    from datetime import datetime

    if not slack_context:
        return "Error: No Slack context available."

    user_id = slack_context.get("user_id", "unknown")
    manager = ReminderManager()
    reminders = manager.get_user_reminders(user_id)

    if not reminders:
        return "You have no active reminders."

    # Get current time in user's timezone
    now = datetime.now(USER_TIMEZONE)
    tz_name = now.strftime("%Z")  # PST or PDT

    lines = [f"You have {len(reminders)} active reminder(s):\n"]
    for r in reminders:
        fire_time = datetime.fromisoformat(r["next_fire_time"])
        cadence = r["cadence"]

        # Format cadence nicely
        if cadence == "once":
            cadence_text = "one-time"
        elif cadence == "daily":
            cadence_text = "daily"
        elif cadence.startswith("weekly_"):
            day = cadence.split("_")[1].capitalize()
            cadence_text = f"every {day}"
        elif cadence.startswith("monthly_"):
            day_num = cadence.split("_")[1]
            cadence_text = f"monthly on the {day_num}"
        else:
            cadence_text = cadence

        lines.append(f"**ID {r['id']}:** \"{r['message']}\"")
        lines.append(f"Next: **{fire_time.strftime('%Y-%m-%d at %I:%M %p')} {tz_name}** ({cadence_text})")
        lines.append("")

    return "\n".join(lines).strip()


def _cancel_reminder(reminder_id: int, slack_context: dict) -> str:
    """Cancel a reminder."""
    from reminders import ReminderManager

    if not slack_context:
        return "Error: No Slack context available."

    if not reminder_id:
        return "Error: reminder_id is required."

    user_id = slack_context.get("user_id", "unknown")
    manager = ReminderManager()

    if manager.cancel_reminder(reminder_id, user_id):
        return f"Reminder {reminder_id} has been cancelled."
    else:
        return f"Could not cancel reminder {reminder_id}. Either it doesn't exist or it's not yours to cancel."

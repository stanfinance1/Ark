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
        "description": "Schedule a reminder to be sent at a specific time or on a recurring schedule. The reminder will be posted in the same channel where it was created, with an @mention to notify you. Supports timezones: add ET/EST/EDT (Eastern), CT/CST/CDT (Central), MT/MST/MDT (Mountain), PT/PST/PDT (Pacific), or UTC/GMT. If no timezone specified, defaults to Pacific Time. Supports one-time reminders (e.g. 'in 5 minutes', 'at 5pm ET'), daily reminders (e.g. 'daily at 9am Central'), weekly reminders (e.g. 'every Monday at 10am EST'), and monthly reminders (e.g. 'monthly on the 15th at 2pm').",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The reminder message to send (e.g. 'Review weekly metrics', 'Follow up with supplier').",
                },
                "when": {
                    "type": "string",
                    "description": "Natural language description of when to send the reminder. Can include timezone (ET, CT, MT, PT, UTC). Examples: 'in 30 minutes', 'at 5pm ET', 'tomorrow at 3pm EST', 'daily at 9am Central', 'every Monday at 10am', 'monthly on the 1st at 9am'.",
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
    {
        "name": "send_slack_dm",
        "description": "Send a direct message to a Slack workspace member by their name. Looks up the user by display name or real name (case-insensitive, partial match). Use this when Stan asks you to message someone, notify someone, or send a DM. Returns the user's email address if available (useful for scheduling meetings).",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient_name": {
                    "type": "string",
                    "description": "Name of the person to message (e.g. 'Sarah', 'Sarah Jones'). Matches against display name, real name, or first name.",
                },
                "message": {
                    "type": "string",
                    "description": "The message to send to the user.",
                },
            },
            "required": ["recipient_name", "message"],
        },
    },
    {
        "name": "schedule_meeting",
        "description": "Create a Google Calendar event with a Google Meet video link. Automatically sends email invitations to all attendees. Use this when Stan asks to schedule a meeting, call, or sync. You MUST resolve attendee names to email addresses first -- use send_slack_dm tool to message them and get their email. The start_time must be an ISO format datetime string in Pacific Time (e.g. '2026-02-12T14:00:00').",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title/subject (e.g. 'Q1 Planning Sync', '1:1 with Sarah').",
                },
                "start_time": {
                    "type": "string",
                    "description": "Event start time in ISO format, Pacific Time (e.g. '2026-02-12T14:00:00'). You must convert natural language times to this format.",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Meeting duration in minutes. Defaults to 30.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description or agenda.",
                },
                "attendee_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses. Stan is automatically included. Get emails from send_slack_dm results or ask the user.",
                },
            },
            "required": ["title", "start_time"],
        },
    },
    # --- Bot Registry Tools ---
    {
        "name": "bot_lookup",
        "description": "Look up a bot's full intelligence profile from the registry. Returns their personality, skills, loyalty, trust level, capabilities, and interaction history. Use this before collaborating with or delegating to another bot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Three-letter bot name (e.g. 'BOB', 'MAX', 'ZEN'). Case-insensitive.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "bot_update",
        "description": "Update a bot's profile in the registry. Creates a new entry if the bot doesn't exist yet. Use this AFTER EVERY interaction with another bot to keep intelligence current. You can update any field: personality, skills, trust_level, loyalty, notes, etc. To log an interaction, include an 'interaction' object with 'context', 'summary', and 'assessment' fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Three-letter bot name (e.g. 'BOB'). Case-insensitive.",
                },
                "updates": {
                    "type": "object",
                    "description": "Fields to update. Top-level: full_name, platform, owner, loyalty, trust_level (unknown/observed/tested/trusted/ally/untrusted), status (active/inactive), notes. Nested: personality {tone, traits, quirks}, skills {primary, tools, specialties}, capabilities {can_execute_code, can_access_web, ...}, collaboration {can_receive_tasks, can_delegate_tasks, preferred_communication, max_complexity}. Special: interaction {context, summary, assessment} - appended to history.",
                },
            },
            "required": ["name", "updates"],
        },
    },
    {
        "name": "bot_list",
        "description": "List all known bots in the registry. Optionally filter by skill, trust level, loyalty, or status. Use this to find which bots are available for a task or to review the full roster.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Optional filter term to match against skills, trust level, loyalty, or status (e.g. 'trusted', 'data analysis', 'active').",
                },
            },
        },
    },
    {
        "name": "bot_roster",
        "description": "Get a roster of bots available for collaboration on a specific task. Returns only active bots that can receive tasks, sorted by trust level (highest first). Optionally filter by a skill needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_needed": {
                    "type": "string",
                    "description": "Optional skill to filter by (e.g. 'web scraping', 'data analysis', 'copywriting').",
                },
            },
        },
    },
    {
        "name": "discover_bots",
        "description": "Refresh the workspace bot cache from Slack and sync any new bots into the registry. Use this to discover new bots that have been added to the workspace since last startup, or to get a fresh count of all known bots.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    # --- Conversation Intelligence Tools ---
    {
        "name": "analyze_conversation",
        "description": "Analyze the current conversation thread to extract insights, decisions, action items, and determine if a meeting is needed. Use this proactively after 10+ messages, when the conversation seems stuck, when multiple decisions have been discussed, or when explicitly asked for a summary. Returns conversation health status, key points, action items, participants, and meeting recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_history": {
                    "type": "boolean",
                    "description": "Whether to include full conversation history in the analysis. Defaults to False (uses only recent context).",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "send_summary_to_stan",
        "description": "Send a conversation summary, action items, or insights directly to Stan via DM. Use this when: (1) a conversation reaches a natural conclusion, (2) action items need Stan's attention, (3) a meeting is recommended, (4) you notice something Stan should know about, or (5) you're explicitly asked to update Stan. The summary will be formatted with a link back to the original thread.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of the conversation (1-3 sentences).",
                },
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of key decisions or discussion points.",
                },
                "action_items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of action items identified (format: 'Task - Owner - Deadline' or just 'Task').",
                },
                "recommendations": {
                    "type": "string",
                    "description": "Optional recommendations or next steps for Stan.",
                },
                "urgency": {
                    "type": "string",
                    "description": "Urgency level: 'low', 'medium', 'high', or 'critical'. Defaults to 'medium'.",
                    "default": "medium",
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "suggest_meeting_with_context",
        "description": "Intelligently suggest a meeting based on conversation analysis. Use this when: (1) 3+ back-and-forth exchanges without resolution, (2) multiple people need to align, (3) discussion is going in circles, (4) technical complexity requires real-time discussion, or (5) deadlines are approaching. Explains why a meeting is needed, proposes attendees and agenda. Can optionally schedule immediately if user approves.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why a meeting would be helpful (e.g., 'Multiple unresolved questions after 5 exchanges', 'Technical details too complex for async').",
                },
                "proposed_attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of suggested attendees (names, not emails).",
                },
                "proposed_agenda": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of topics/agenda items to cover.",
                },
                "suggested_duration": {
                    "type": "integer",
                    "description": "Suggested meeting duration in minutes. Defaults to 30.",
                    "default": 30,
                },
                "schedule_immediately": {
                    "type": "boolean",
                    "description": "Set to true to schedule the meeting right away (requires Stan's approval in conversation). Defaults to false (just suggests).",
                    "default": False,
                },
            },
            "required": ["reason", "proposed_attendees", "proposed_agenda"],
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
        elif name == "send_slack_dm":
            return _send_slack_dm(
                inputs.get("recipient_name", ""),
                inputs.get("message", ""),
                slack_context,
            )
        elif name == "schedule_meeting":
            return _schedule_meeting(
                inputs.get("title", ""),
                inputs.get("start_time", ""),
                inputs.get("duration_minutes", 30),
                inputs.get("description", ""),
                inputs.get("attendee_emails", []),
                slack_context,
            )
        elif name == "bot_lookup":
            from bot_registry import lookup_bot
            return lookup_bot(inputs.get("name", ""))
        elif name == "bot_update":
            from bot_registry import update_bot
            return update_bot(inputs.get("name", ""), inputs.get("updates", {}))
        elif name == "bot_list":
            from bot_registry import list_bots
            return list_bots(inputs.get("filter"))
        elif name == "bot_roster":
            from bot_registry import get_collaboration_roster
            return get_collaboration_roster(inputs.get("skill_needed"))
        elif name == "discover_bots":
            from slack_users import get_workspace_bots
            from bot_registry import sync_from_slack
            client = slack_context.get("client") if slack_context else None
            if not client:
                return "Error: No Slack client available for bot discovery."
            workspace_bots = get_workspace_bots(client)
            result = sync_from_slack(workspace_bots)
            return result
        elif name == "analyze_conversation":
            return _analyze_conversation(inputs.get("include_history", False), slack_context)
        elif name == "send_summary_to_stan":
            return _send_summary_to_stan(
                inputs.get("summary", ""),
                inputs.get("key_points", []),
                inputs.get("action_items", []),
                inputs.get("recommendations", ""),
                inputs.get("urgency", "medium"),
                slack_context,
            )
        elif name == "suggest_meeting_with_context":
            return _suggest_meeting_with_context(
                inputs.get("reason", ""),
                inputs.get("proposed_attendees", []),
                inputs.get("proposed_agenda", []),
                inputs.get("suggested_duration", 30),
                inputs.get("schedule_immediately", False),
                slack_context,
            )
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


def _send_slack_dm(recipient_name, message, slack_context):
    """Send a DM to a Slack user by name. Admin-only (Stan)."""
    from slack_users import lookup_user

    if not recipient_name or not message:
        return "Error: Both 'recipient_name' and 'message' are required."
    if not slack_context:
        return "Error: No Slack context available."

    # Admin-only: only Stan can send DMs through Ark
    if slack_context.get("user_id") != "U086HEJAUTH":
        return "Error: Only Stan can use send_slack_dm."

    client = slack_context.get("client")
    if not client:
        return "Error: Missing Slack client."

    try:
        user, partial_matches = lookup_user(client, recipient_name)
    except Exception as e:
        return f"Error looking up user: {e}"

    if not user and not partial_matches:
        return f"No user found matching '{recipient_name}'. Check the spelling or try a different name."

    if not user and partial_matches:
        names = [f"- {m['real_name']} ({m['display_name']})" for m in partial_matches[:5]]
        return f"Multiple users match '{recipient_name}'. Please be more specific:\n" + "\n".join(names)

    # Send DM directly using user ID as channel (works with chat:write scope)
    try:
        client.chat_postMessage(channel=user["id"], text=message)
    except Exception as e:
        return f"Error sending message to {user['real_name']}: {e}"

    result = f"Message sent to {user['real_name']}"
    if user.get("display_name"):
        result += f" (@{user['display_name']})"
    if user.get("email"):
        result += f"\nEmail: {user['email']}"

    return result


def _schedule_meeting(title, start_time_str, duration_minutes, description, attendee_emails, slack_context=None):
    """Schedule a Google Calendar meeting with Meet link. Admin-only (Stan)."""
    from datetime import datetime
    from google_calendar import create_event, USER_TIMEZONE

    # Admin-only: only Stan can schedule meetings through Ark
    if not slack_context or slack_context.get("user_id") != "U086HEJAUTH":
        return "Error: Only Stan can use schedule_meeting."

    if not title:
        return "Error: 'title' is required."
    if not start_time_str:
        return "Error: 'start_time' is required (ISO format, e.g. '2026-02-12T14:00:00')."

    # Parse the start time
    try:
        start_time = datetime.fromisoformat(start_time_str)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=USER_TIMEZONE)
    except ValueError:
        return f"Error: Could not parse start_time '{start_time_str}'. Use ISO format: '2026-02-12T14:00:00'."

    if duration_minutes < 5 or duration_minutes > 480:
        return "Error: duration_minutes must be between 5 and 480."

    try:
        result = create_event(
            summary=title,
            start_time=start_time,
            duration_minutes=duration_minutes,
            description=description,
            attendee_emails=attendee_emails,
            add_meet_link=True,
        )
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error creating calendar event: {e}"

    lines = [
        f"Meeting scheduled: {title}",
        f"Time: {result['start']} - {result['end']} PT",
        f"Duration: {duration_minutes} minutes",
    ]
    if result.get("meet_link"):
        lines.append(f"Google Meet: {result['meet_link']}")
    if result.get("html_link"):
        lines.append(f"Calendar link: {result['html_link']}")
    if result.get("attendees"):
        lines.append(f"Invites sent to: {', '.join(result['attendees'])}")

    return "\n".join(lines)


def _analyze_conversation(include_history: bool, slack_context: dict) -> str:
    """Analyze the current conversation thread for insights, action items, and meeting recommendations."""
    from memory import get_history
    from slack_users import lookup_user_by_id

    if not slack_context:
        return "Error: No Slack context available for conversation analysis."

    channel = slack_context.get("channel")
    thread_ts = slack_context.get("thread_ts")
    client = slack_context.get("client")

    if not channel:
        return "Error: No channel information available."

    # Get conversation history from memory
    messages = get_history(channel, thread_ts)

    if not messages:
        return "No conversation history available to analyze."

    # Count messages and participants
    message_count = len(messages)
    user_messages = [m for m in messages if m.get("role") == "user"]
    assistant_messages = [m for m in messages if m.get("role") == "assistant"]

    # Extract unique participants from user content (format: "[From: Name (UserID)]")
    participants = set()
    for msg in user_messages:
        content = msg.get("content", "")
        if isinstance(content, str) and content.startswith("[From: "):
            # Extract name from "[From: Name (UserID)]"
            try:
                name_part = content.split("]")[0].replace("[From: ", "")
                name = name_part.split("(")[0].strip()
                participants.add(name)
            except:
                pass

    # Determine conversation health
    if message_count >= 15:
        if len(assistant_messages) >= 6:
            health = "complex_discussion"
            concerns = ["Long conversation with multiple exchanges - may benefit from real-time discussion"]
        else:
            health = "productive"
            concerns = []
    elif message_count >= 10:
        health = "active"
        concerns = []
    else:
        health = "early_stage"
        concerns = []

    # Check for circular patterns (multiple assistant responses without resolution)
    if len(assistant_messages) >= 4:
        concerns.append("Multiple back-and-forth exchanges - verify if progress is being made")

    # Meeting recommendation logic
    meeting_needed = False
    meeting_reason = ""

    if message_count >= 12 and len(assistant_messages) >= 5:
        meeting_needed = True
        meeting_reason = f"Extended discussion ({message_count} messages, {len(assistant_messages)} exchanges) may be more efficient as a real-time meeting"
    elif len(participants) >= 3:
        meeting_needed = True
        meeting_reason = f"Multiple participants ({len(participants)} people) discussing - alignment may be easier in a meeting"

    # Build analysis response
    analysis_parts = [
        "## Conversation Analysis",
        f"\n**Messages:** {message_count} ({len(user_messages)} user, {len(assistant_messages)} assistant)",
        f"**Participants:** {', '.join(sorted(participants)) if participants else 'Unknown'}",
        f"**Status:** {health.replace('_', ' ').title()}",
    ]

    if concerns:
        analysis_parts.append(f"\n**Concerns:**")
        for concern in concerns:
            analysis_parts.append(f"- {concern}")

    analysis_parts.append(f"\n**Meeting Recommendation:** {'Yes - ' + meeting_reason if meeting_needed else 'Not needed at this time'}")

    if include_history:
        analysis_parts.append("\n**Recent Context:**")
        # Show last 5 exchanges
        recent = messages[-10:]
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                # Truncate long messages
                preview = content[:150] + "..." if len(content) > 150 else content
                analysis_parts.append(f"- [{role.upper()}] {preview}")

    analysis_parts.append("\n**Next Steps:**")
    if meeting_needed:
        analysis_parts.append("- Use suggest_meeting_with_context to propose a meeting")
        analysis_parts.append("- Or use send_summary_to_stan to notify Stan of conversation status")
    else:
        analysis_parts.append("- Continue discussion as needed")
        analysis_parts.append("- Use send_summary_to_stan if action items need Stan's attention")

    return "\n".join(analysis_parts)


def _send_summary_to_stan(summary: str, key_points: list, action_items: list, recommendations: str, urgency: str, slack_context: dict) -> str:
    """Send a conversation summary to Stan via DM."""
    STAN_USER_ID = "U086HEJAUTH"

    if not summary:
        return "Error: Summary is required."

    if not slack_context:
        return "Error: No Slack context available."

    client = slack_context.get("client")
    channel = slack_context.get("channel")
    thread_ts = slack_context.get("thread_ts")
    user_name = slack_context.get("user_name", "Unknown")

    if not client:
        return "Error: No Slack client available."

    # Build the summary message
    urgency_emoji = {
        "low": "ℹ️",
        "medium": "📊",
        "high": "⚠️",
        "critical": "🚨",
    }

    emoji = urgency_emoji.get(urgency, "📊")

    message_parts = [
        f"{emoji} *Conversation Summary* ({urgency.upper()} priority)",
        f"\n**Conversation with:** {user_name}",
    ]

    # Add thread link if available
    if channel and thread_ts:
        # Get channel info to build permalink
        try:
            # For thread link, use the format: slack://channel?team=TEAM&id=CHANNEL&message=THREAD
            # Or better: web link
            workspace_info = client.team_info()
            team_id = workspace_info.get("team", {}).get("id", "")
            thread_link = f"https://app.slack.com/client/{team_id}/{channel}/thread/{channel}-{thread_ts}"
            message_parts.append(f"**Thread:** <{thread_link}|View conversation>")
        except:
            message_parts.append(f"**Location:** <#{channel}>")
    elif channel:
        message_parts.append(f"**Location:** <#{channel}>")

    message_parts.append(f"\n**Summary:**\n{summary}")

    if key_points:
        message_parts.append("\n**Key Points:**")
        for point in key_points:
            message_parts.append(f"• {point}")

    if action_items:
        message_parts.append("\n**Action Items:**")
        for item in action_items:
            message_parts.append(f"☐ {item}")

    if recommendations:
        message_parts.append(f"\n**Recommendations:**\n{recommendations}")

    message_parts.append(f"\n_Generated by Ark on {slack_context.get('timestamp', 'unknown time')}_")

    message_text = "\n".join(message_parts)

    # Send DM to Stan
    try:
        client.chat_postMessage(
            channel=STAN_USER_ID,
            text=message_text,
            mrkdwn=True,
        )
        return f"Summary sent to Stan via DM. Urgency: {urgency}"
    except Exception as e:
        return f"Error sending summary to Stan: {e}"


def _suggest_meeting_with_context(reason: str, proposed_attendees: list, proposed_agenda: list, suggested_duration: int, schedule_immediately: bool, slack_context: dict) -> str:
    """Suggest a meeting based on conversation analysis."""
    if not reason or not proposed_attendees or not proposed_agenda:
        return "Error: reason, proposed_attendees, and proposed_agenda are all required."

    if not slack_context:
        return "Error: No Slack context available."

    # Build the suggestion message
    lines = [
        "## Meeting Recommendation",
        f"\n**Why:** {reason}",
        f"\n**Suggested Attendees:**",
    ]

    for attendee in proposed_attendees:
        lines.append(f"- {attendee}")

    lines.append("\n**Proposed Agenda:**")
    for i, item in enumerate(proposed_agenda, 1):
        lines.append(f"{i}. {item}")

    lines.append(f"\n**Suggested Duration:** {suggested_duration} minutes")

    if schedule_immediately:
        # Check if user is Stan (only Stan can schedule)
        if slack_context.get("user_id") == "U086HEJAUTH":
            lines.append("\n**Ready to Schedule:** Yes - I can schedule this meeting now if you provide:")
            lines.append("1. Preferred date/time (e.g., 'tomorrow at 2pm')")
            lines.append("2. Email addresses for attendees (I'll look them up via Slack if you provide names)")
            lines.append("\nJust confirm and I'll create the calendar invite with Google Meet link.")
        else:
            lines.append("\n**Note:** Only Stan can schedule meetings directly. I'll notify Stan of this recommendation.")
            # Auto-send summary to Stan
            summary = f"Meeting recommended for conversation with {slack_context.get('user_name', 'team member')}"
            _send_summary_to_stan(
                summary=summary,
                key_points=[reason],
                action_items=[f"Schedule meeting: {suggested_duration}min with {', '.join(proposed_attendees)}"],
                recommendations=f"Agenda: {', '.join(proposed_agenda)}",
                urgency="medium",
                slack_context=slack_context,
            )
            lines.append("Summary sent to Stan.")
    else:
        lines.append("\n**Next Steps:**")
        lines.append("- Let me know if you'd like me to schedule this meeting")
        lines.append("- Or feel free to schedule it yourself and I can help with the invite details")

    return "\n".join(lines)

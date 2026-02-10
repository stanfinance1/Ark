"""
Ark - Tool definitions and execution.
Defines tools for Claude API tool use, and executes them when called.
"""

import subprocess
import os
import sys
import tempfile

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

from config import BASE_DIR, TMP_DIR

PYTHON = sys.executable

# Tool definitions in Claude API format
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
        "description": "Search the internet using DuckDuckGo. Returns top results with titles, URLs, and snippets. Use this for weather, news, prices, company info, or any real-time information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'NYC weather today', 'AAPL stock price', 'latest AI news').",
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
        "description": "Fetch a web page and extract its text content. Use this after web_search to read a specific page, or when a user shares a URL they want you to read.",
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
]


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
            return _upload_file(
                inputs.get("path", ""),
                inputs.get("title", ""),
                slack_context,
            )
        elif name == "web_search":
            return _web_search(inputs.get("query", ""), inputs.get("max_results", 5))
        elif name == "fetch_url":
            return _fetch_url(inputs.get("url", ""), inputs.get("max_chars", 5000))
        else:
            return f"Error: Unknown tool '{name}'"
    except Exception as e:
        return f"Error executing {name}: {str(e)}"


def _run_python(code: str, description: str = "") -> str:
    """Execute Python code in a subprocess and return stdout + stderr."""
    # Prepend helper variables so the code knows about project paths
    header = f"""
import sys
import os
TMP_DIR = r"{TMP_DIR}"
BASE_DIR = r"{BASE_DIR}"
os.makedirs(TMP_DIR, exist_ok=True)
"""
    full_code = header + "\n" + code

    # Write to temp file and execute
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=TMP_DIR, delete=False
    ) as f:
        f.write(full_code)
        script_path = f.name

    try:
        result = subprocess.run(
            [PYTHON, script_path],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=BASE_DIR,
        )
        output = ""
        if result.stdout:
            output += result.stdout
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
                size = os.path.getsize(full)
                entries.append(f"  {entry} ({_human_size(size)})")
        return f"Contents of {path}:\n" + "\n".join(entries)
    except Exception as e:
        return f"Error listing directory: {e}"


def _upload_file(path: str, title: str, slack_context: dict) -> str:
    """Upload a file to Slack. Requires slack_context with client + channel."""
    if not slack_context:
        return "Error: No Slack context available for file upload."
    if not os.path.exists(path):
        return f"Error: File not found: {path}"

    client = slack_context.get("client")
    channel = slack_context.get("channel")
    thread_ts = slack_context.get("thread_ts")

    if not client or not channel:
        return "Error: Missing Slack client or channel."

    try:
        client.files_upload_v2(
            channel=channel,
            file=path,
            title=title or os.path.basename(path),
            thread_ts=thread_ts,
        )
        return f"Uploaded {os.path.basename(path)} to Slack."
    except Exception as e:
        return f"Error uploading file: {e}"


def _web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo and return results."""
    if not query:
        return "Error: No search query provided."
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return f"No results found for: {query}"
        output = []
        for i, r in enumerate(results, 1):
            output.append(f"{i}. {r.get('title', 'No title')}")
            output.append(f"   URL: {r.get('href', '')}")
            output.append(f"   {r.get('body', '')}")
            output.append("")
        return "\n".join(output).strip()
    except Exception as e:
        return f"Error searching web: {e}"


def _fetch_url(url: str, max_chars: int = 5000) -> str:
    """Fetch a URL and extract readable text content."""
    if not url:
        return "Error: No URL provided."
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Ark-Bot/1.0)"
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n... (truncated)"
        return text or "(page had no readable text)"
    except Exception as e:
        return f"Error fetching URL: {e}"


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.0f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"

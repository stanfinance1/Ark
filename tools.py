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

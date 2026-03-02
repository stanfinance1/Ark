"""
Shared Memory - Supabase client for Claude Code <-> Ark bridge.
Used by both Ark (brain.py, tools.py) and Claude Code (shared_memory_bridge.py).
"""

import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_client = None


def get_client():
    """Lazy-init Supabase client. Returns None if not configured."""
    global _client
    if _client is not None:
        return _client

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()

    if not url or not key:
        logger.warning("Supabase not configured (missing SUPABASE_URL or SUPABASE_KEY)")
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
        logger.info("Supabase client initialized")
        return _client
    except Exception as e:
        logger.error(f"Failed to init Supabase: {e}")
        return None


# --- shared_memory table ---

def store_memory(category: str, key: str, value: str, source: str = "claude_code") -> bool:
    """Upsert a key-value pair into shared_memory. Returns True on success."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("shared_memory").upsert({
            "category": category,
            "key": key,
            "value": value,
            "source": source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="category,key").execute()
        return True
    except Exception as e:
        logger.error(f"store_memory failed: {e}")
        return False


def get_memory(category: str = None, key: str = None) -> list:
    """Read from shared_memory. Filter by category and/or key. Returns list of dicts."""
    client = get_client()
    if not client:
        return []
    try:
        q = client.table("shared_memory").select("*")
        if category:
            q = q.eq("category", category)
        if key:
            q = q.eq("key", key)
        result = q.order("updated_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"get_memory failed: {e}")
        return []


def search_memory(query: str) -> list:
    """Text search across shared_memory values (case-insensitive LIKE)."""
    client = get_client()
    if not client:
        return []
    try:
        result = client.table("shared_memory").select("*").ilike("value", f"%{query}%").execute()
        return result.data or []
    except Exception as e:
        logger.error(f"search_memory failed: {e}")
        return []


# --- conversation_log table ---

def log_conversation(channel: str, thread_ts: str, user_name: str, summary: str,
                     key_points: list = None, action_items: list = None,
                     model_used: str = None) -> bool:
    """Insert a conversation summary into conversation_log. Returns True on success."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("conversation_log").insert({
            "channel": channel,
            "thread_ts": thread_ts,
            "user_name": user_name,
            "summary": summary,
            "key_points": json.dumps(key_points or []),
            "action_items": json.dumps(action_items or []),
            "model_used": model_used,
        }).execute()
        return True
    except Exception as e:
        logger.error(f"log_conversation failed: {e}")
        return False


def get_recent_conversations(limit: int = 10) -> list:
    """Get latest conversation summaries."""
    client = get_client()
    if not client:
        return []
    try:
        result = (client.table("conversation_log")
                  .select("*")
                  .order("created_at", desc=True)
                  .limit(limit)
                  .execute())
        return result.data or []
    except Exception as e:
        logger.error(f"get_recent_conversations failed: {e}")
        return []


# --- task_log table ---

def log_task(source: str, task_name: str, description: str = None,
             outcome: str = None, files_created: list = None) -> bool:
    """Insert a completed task into task_log. Returns True on success."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("task_log").insert({
            "source": source,
            "task_name": task_name,
            "description": description,
            "outcome": outcome,
            "files_created": json.dumps(files_created or []),
        }).execute()
        return True
    except Exception as e:
        logger.error(f"log_task failed: {e}")
        return False


def get_recent_tasks(limit: int = 10, source: str = None) -> list:
    """Get latest tasks. Optionally filter by source ('claude_code' or 'ark')."""
    client = get_client()
    if not client:
        return []
    try:
        q = client.table("task_log").select("*").order("created_at", desc=True).limit(limit)
        if source:
            q = q.eq("source", source)
        result = q.execute()
        return result.data or []
    except Exception as e:
        logger.error(f"get_recent_tasks failed: {e}")
        return []


# --- daily_metrics table ---

def get_daily_metric(date: str, source: str) -> dict | None:
    """Get daily metrics for a specific date and source.
    Args:
        date: YYYY-MM-DD (Pacific calendar day)
        source: 'shopify_dtc' | 'shopify_wholesale' | 'meta_ads'
    Returns: dict of metrics or None if not found.
    """
    client = get_client()
    if not client:
        return None
    try:
        result = (client.table("daily_metrics")
                  .select("data,date,source,updated_at")
                  .eq("date", date)
                  .eq("source", source)
                  .execute())
        if not result.data:
            return None
        row = result.data[0]
        data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
        data["_date"] = row["date"]
        data["_source"] = row["source"]
        data["_cached_at"] = row["updated_at"]
        return data
    except Exception as e:
        logger.error(f"get_daily_metric failed: {e}")
        return None


def set_daily_metric(date: str, source: str, data: dict) -> bool:
    """Upsert daily metrics for a specific date and source."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("daily_metrics").upsert({
            "date": date,
            "source": source,
            "data": json.dumps(data) if isinstance(data, dict) else data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="date,source").execute()
        return True
    except Exception as e:
        logger.error(f"set_daily_metric failed: {e}")
        return False


def get_date_range_metrics(source: str, start_date: str, end_date: str) -> list:
    """Get daily metrics for a date range, sorted by date.
    Args:
        source: 'shopify_dtc' | 'shopify_wholesale' | 'meta_ads'
        start_date: YYYY-MM-DD (inclusive)
        end_date: YYYY-MM-DD (inclusive)
    Returns: list of dicts with 'date' + metric fields.
    """
    client = get_client()
    if not client:
        return []
    try:
        result = (client.table("daily_metrics")
                  .select("date,data,updated_at")
                  .eq("source", source)
                  .gte("date", start_date)
                  .lte("date", end_date)
                  .order("date")
                  .execute())
        rows = result.data or []
        out = []
        for row in rows:
            d = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
            entry = {"date": row["date"]}
            entry.update(d)
            out.append(entry)
        return out
    except Exception as e:
        logger.error(f"get_date_range_metrics failed: {e}")
        return []


# --- financial_statements table ---

def get_financial_statement(period_month: str, statement_type: str) -> dict | None:
    """Get a single monthly financial statement.
    Args:
        period_month: 'YYYY-MM' (e.g. '2026-01')
        statement_type: 'pnl_actuals' | 'pnl_budget' | 'cash_flow'
    Returns: dict with all financial line items, or None if not found.
    """
    client = get_client()
    if not client:
        return None
    try:
        result = (client.table("financial_statements")
                  .select("data,period_month,statement_type,updated_at")
                  .eq("period_month", period_month)
                  .eq("statement_type", statement_type)
                  .execute())
        if not result.data:
            return None
        row = result.data[0]
        data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
        data["_period_month"] = row["period_month"]
        data["_statement_type"] = row["statement_type"]
        data["_cached_at"] = row["updated_at"]
        return data
    except Exception as e:
        logger.error(f"get_financial_statement failed: {e}")
        return None


def set_financial_statement(period_month: str, statement_type: str, data: dict) -> bool:
    """Upsert a monthly financial statement."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("financial_statements").upsert({
            "period_month": period_month,
            "statement_type": statement_type,
            "data": json.dumps(data) if isinstance(data, dict) else data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="period_month,statement_type").execute()
        return True
    except Exception as e:
        logger.error(f"set_financial_statement failed: {e}")
        return False


def get_financial_statement_range(statement_type: str,
                                  start_month: str, end_month: str) -> list:
    """Get financial statements for a month range, sorted by period_month.
    Args:
        statement_type: 'pnl_actuals' | 'pnl_budget' | 'cash_flow'
        start_month: 'YYYY-MM' (inclusive)
        end_month: 'YYYY-MM' (inclusive)
    Returns: list of dicts, each with 'period_month' + all financial fields.
    """
    client = get_client()
    if not client:
        return []
    try:
        result = (client.table("financial_statements")
                  .select("period_month,data,updated_at")
                  .eq("statement_type", statement_type)
                  .gte("period_month", start_month)
                  .lte("period_month", end_month)
                  .order("period_month")
                  .execute())
        rows = result.data or []
        out = []
        for row in rows:
            d = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
            entry = {"period_month": row["period_month"]}
            entry.update(d)
            out.append(entry)
        return out
    except Exception as e:
        logger.error(f"get_financial_statement_range failed: {e}")
        return []


# --- Context loader (for Ark brain auto-inject) ---

def load_shared_context(max_convos: int = 5, max_tasks: int = 5) -> str:
    """Build a context string from recent shared memory for injection into Ark's brain.
    Returns empty string if Supabase is unavailable."""
    parts = []

    # Recent decisions/facts
    memories = get_memory(category="decision")
    memories += get_memory(category="fact")
    if memories:
        parts.append("## Recent Shared Knowledge")
        for m in memories[:10]:
            parts.append(f"- [{m['category']}] {m['key']}: {m['value']}")

    # Recent tasks (from both systems)
    tasks = get_recent_tasks(limit=max_tasks)
    if tasks:
        parts.append("\n## Recent Tasks (Claude Code + Ark)")
        for t in tasks:
            ts = t['created_at'][:10] if t.get('created_at') else '?'
            parts.append(f"- [{ts}] ({t['source']}) {t['task_name']}")

    # Recent conversations
    convos = get_recent_conversations(limit=max_convos)
    if convos:
        parts.append("\n## Recent Ark Conversations")
        for c in convos:
            ts = c['created_at'][:16] if c.get('created_at') else '?'
            user = c.get('user_name', '?')
            parts.append(f"- [{ts}] {user}: {c['summary'][:120]}")

    if not parts:
        return ""
    return "\n".join(parts)


# --- tool_registry + tool_usage_log tables ---

def log_tool_usage(tool_name: str, system: str, invoked_by: str = None,
                   success: bool = True, duration_ms: int = None) -> bool:
    """Log a tool invocation to tool_usage_log.
    The DB trigger auto-bumps use_count/last_used_at on tool_registry."""
    client = get_client()
    if not client:
        return False
    try:
        row = {
            "tool_name": tool_name,
            "system": system,
            "success": success,
        }
        if invoked_by:
            row["invoked_by"] = invoked_by
        if duration_ms is not None:
            row["duration_ms"] = duration_ms
        client.table("tool_usage_log").insert(row).execute()
        return True
    except Exception as e:
        logger.error(f"log_tool_usage failed: {e}")
        return False


def register_tool(name: str, system: str, group_name: str = None,
                  description: str = "", file_path: str = None) -> bool:
    """Register a new tool (or update existing) in tool_registry.
    Call this when creating new tools to auto-populate the registry."""
    client = get_client()
    if not client:
        return False
    try:
        row = {
            "name": name,
            "system": system,
            "description": description,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if group_name:
            row["group_name"] = group_name
        if file_path:
            row["file_path"] = file_path
        client.table("tool_registry").upsert(row, on_conflict="name").execute()
        return True
    except Exception as e:
        logger.error(f"register_tool failed: {e}")
        return False


def get_tool_registry(system: str = None, group_name: str = None) -> list:
    """Get tools from registry, optionally filtered by system or group."""
    client = get_client()
    if not client:
        return []
    try:
        q = client.table("tool_registry").select("*").order("system").order("group_name").order("name")
        if system:
            q = q.eq("system", system)
        if group_name:
            q = q.eq("group_name", group_name)
        result = q.execute()
        return result.data or []
    except Exception as e:
        logger.error(f"get_tool_registry failed: {e}")
        return []

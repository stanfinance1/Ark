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


# --- bi_cache table ---

# TTL per metric type (seconds). Historical data stays longer.
_BI_TTL = {
    "shopify_today": 900,       # 15 min - active data changes
    "shopify_yesterday": 21600, # 6 hours - finalized
    "shopify_": 3600,           # 1 hour - default for other shopify timeframes
    "meta_ads_": 1800,          # 30 min
    "skio_": 3600,              # 1 hour
}


def _get_ttl(cache_key: str) -> int:
    """Get TTL for a cache key based on prefix matching."""
    for prefix, ttl in _BI_TTL.items():
        if cache_key.startswith(prefix):
            return ttl
    return 900  # 15 min default


def get_bi_cache(metric_type: str, timeframe: str) -> str | None:
    """Get cached BI data from Supabase. Returns None if stale or missing."""
    client = get_client()
    if not client:
        return None
    try:
        result = (client.table("bi_cache")
                  .select("data,fetched_at")
                  .eq("metric_type", metric_type)
                  .eq("timeframe", timeframe)
                  .execute())
        if not result.data:
            return None
        row = result.data[0]
        fetched_at = datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        cache_key = f"{metric_type}_{timeframe}"
        ttl = _get_ttl(cache_key)
        if age > ttl:
            return None  # stale
        remaining = int(ttl - age)
        return row["data"] + f"\n\n[Cached {int(age)}s ago - refreshes in {remaining}s]"
    except Exception as e:
        logger.error(f"get_bi_cache failed: {e}")
        return None


def set_bi_cache(metric_type: str, timeframe: str, data: str) -> bool:
    """Store BI data in Supabase cache. Upserts."""
    client = get_client()
    if not client:
        return False
    try:
        client.table("bi_cache").upsert({
            "metric_type": metric_type,
            "timeframe": timeframe,
            "data": data,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="metric_type,timeframe").execute()
        return True
    except Exception as e:
        logger.error(f"set_bi_cache failed: {e}")
        return False


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

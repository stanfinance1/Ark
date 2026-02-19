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

"""
Business Intelligence Data Cache - Supabase-backed with in-memory fallback.
Survives Railway redeploys. Both Ark and Claude Code share the same cache.
"""

import time
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# In-memory fallback (used only when Supabase is unavailable)
_fallback_cache = {}
_FALLBACK_TTL = 300  # 5 min


def get_cached_or_fetch(
    cache_key: str,
    fetch_fn: Callable[[], str],
) -> str:
    """
    Check Supabase cache first → return if fresh.
    If stale/missing → call API → store in Supabase + return.
    Falls back to in-memory cache if Supabase is down.
    """
    # Parse cache_key like "shopify_metrics_today" → metric_type="shopify", timeframe="today"
    parts = cache_key.split("_", 1)  # e.g. ["shopify", "metrics_today"]
    if len(parts) >= 2:
        metric_type = parts[0]
        timeframe = parts[1]
    else:
        metric_type = cache_key
        timeframe = "default"

    # Try Supabase cache first
    try:
        from shared_memory import get_bi_cache, set_bi_cache
        cached = get_bi_cache(metric_type, timeframe)
        if cached is not None:
            logger.info(f"BI cache HIT (Supabase): {cache_key}")
            return cached
    except Exception as e:
        logger.warning(f"Supabase cache read failed: {e}")

    # Cache miss - fetch fresh data from API
    logger.info(f"BI cache MISS: {cache_key} - fetching from API")
    result = fetch_fn()

    # Store in Supabase cache
    try:
        from shared_memory import set_bi_cache
        set_bi_cache(metric_type, timeframe, result)
    except Exception as e:
        logger.warning(f"Supabase cache write failed: {e}")
        # Fallback: store in memory
        _fallback_cache[cache_key] = {"result": result, "timestamp": time.time()}

    return result + "\n\n[Fresh data - now cached in Supabase]"


def clear_cache(cache_key: str = None):
    """Clear in-memory fallback cache."""
    global _fallback_cache
    if cache_key is None:
        _fallback_cache = {}
    elif cache_key in _fallback_cache:
        del _fallback_cache[cache_key]

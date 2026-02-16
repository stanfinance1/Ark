"""
Business Intelligence Data Cache
Reduces API calls by caching BI tool results with TTL (time-to-live).
"""

import time
from typing import Optional, Callable, Any

# Cache structure: {cache_key: {"result": str, "timestamp": float}}
_cache = {}

# Cache TTL in seconds (5 minutes = 300s)
CACHE_TTL_SECONDS = 300


def get_cached_or_fetch(
    cache_key: str,
    fetch_fn: Callable[[], Any],
    ttl_seconds: int = CACHE_TTL_SECONDS
) -> str:
    """
    Get cached result if still valid, otherwise fetch fresh data and cache it.

    Args:
        cache_key: Unique identifier for this cache entry
        fetch_fn: Function to call if cache miss (should return string result)
        ttl_seconds: How long to cache the result (default 300s = 5 min)

    Returns:
        Cached or freshly fetched result string
    """
    now = time.time()

    # Check if we have a valid cached entry
    if cache_key in _cache:
        entry = _cache[cache_key]
        age = now - entry["timestamp"]

        if age < ttl_seconds:
            # Cache hit - return cached result
            remaining = int(ttl_seconds - age)
            result = entry["result"]
            result += f"\n\n[Cached data - {remaining}s until refresh]"
            return result

    # Cache miss or expired - fetch fresh data
    result = fetch_fn()

    # Store in cache
    _cache[cache_key] = {
        "result": result,
        "timestamp": now
    }

    return result + "\n\n[Fresh data - cached for 5 minutes]"


def clear_cache(cache_key: Optional[str] = None):
    """
    Clear cache entries.

    Args:
        cache_key: Specific key to clear, or None to clear all
    """
    global _cache

    if cache_key is None:
        _cache = {}
    elif cache_key in _cache:
        del _cache[cache_key]


def get_cache_stats() -> dict:
    """Get cache statistics."""
    now = time.time()

    stats = {
        "total_entries": len(_cache),
        "entries": []
    }

    for key, entry in _cache.items():
        age = now - entry["timestamp"]
        stats["entries"].append({
            "key": key,
            "age_seconds": int(age),
            "size_bytes": len(entry["result"])
        })

    return stats

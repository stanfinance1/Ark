"""
Ark - Slack user lookup with caching.
Caches the full workspace user list (humans + bots) to avoid repeated API calls.
Cache refreshes every 10 minutes.
"""

import time
import logging

logger = logging.getLogger(__name__)

# Module-level caches
_user_cache = []
_bot_cache = []
_bot_id_set = set()  # Quick lookup by user ID
_cache_timestamp = 0
CACHE_TTL_SECONDS = 600  # 10 minutes


def _refresh_cache(client):
    """Fetch all workspace users from Slack and cache them (humans and bots separately)."""
    global _user_cache, _bot_cache, _bot_id_set, _cache_timestamp

    users = []
    bots = []
    cursor = None

    while True:
        kwargs = {"limit": 200}
        if cursor:
            kwargs["cursor"] = cursor

        response = client.users_list(**kwargs)

        for member in response.get("members", []):
            if member.get("deleted"):
                continue

            profile = member.get("profile", {})

            if member.get("is_bot") or member.get("id") == "USLACKBOT":
                # Bot user - store separately
                bots.append({
                    "id": member["id"],
                    "name": profile.get("real_name", "") or member.get("name", ""),
                    "real_name": profile.get("real_name", ""),
                    "display_name": profile.get("display_name", ""),
                    "app_id": profile.get("api_app_id", "") or member.get("profile", {}).get("api_app_id", ""),
                    "is_bot": True,
                })
            else:
                # Human user
                users.append({
                    "id": member["id"],
                    "real_name": profile.get("real_name", ""),
                    "display_name": profile.get("display_name", ""),
                    "first_name": profile.get("first_name", ""),
                    "email": profile.get("email", ""),
                })

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    _user_cache = users
    _bot_cache = bots
    _bot_id_set = {b["id"] for b in bots}
    _cache_timestamp = time.time()
    logger.info(f"Refreshed Slack cache: {len(users)} humans, {len(bots)} bots")
    return users


def _get_users(client):
    """Get users from cache, refreshing if stale."""
    global _user_cache, _cache_timestamp

    if time.time() - _cache_timestamp > CACHE_TTL_SECONDS or not _user_cache:
        return _refresh_cache(client)
    return _user_cache


def lookup_user(client, name):
    """
    Look up a user by name (case-insensitive, partial match).
    Returns (exact_match_or_None, list_of_partial_matches).

    Matching priority:
    1. Exact match on display_name or real_name
    2. First-name match
    3. Partial/substring match on display_name or real_name
    """
    users = _get_users(client)
    name_lower = name.lower().strip()

    exact_matches = []
    first_name_matches = []
    partial_matches = []

    for user in users:
        display = user["display_name"].lower()
        real = user["real_name"].lower()
        first = user["first_name"].lower()

        if name_lower == display or name_lower == real:
            exact_matches.append(user)
        elif name_lower == first:
            first_name_matches.append(user)
        elif name_lower in display or name_lower in real:
            partial_matches.append(user)

    # Exactly one exact match
    if len(exact_matches) == 1:
        return exact_matches[0], []
    elif exact_matches:
        return None, exact_matches

    # Exactly one first-name match
    if len(first_name_matches) == 1:
        return first_name_matches[0], []
    elif first_name_matches:
        return None, first_name_matches

    # Exactly one partial match
    if len(partial_matches) == 1:
        return partial_matches[0], []

    return None, partial_matches


def get_workspace_bots(client):
    """Get all bot users from the workspace cache."""
    _get_users(client)  # Ensure cache is fresh
    return list(_bot_cache)


def is_bot_user(client, user_id):
    """Check if a user ID belongs to a bot. Uses cached data."""
    _get_users(client)  # Ensure cache is fresh
    return user_id in _bot_id_set

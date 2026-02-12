"""
Ark - Bot Registry. Stores and manages intelligence on other bots.
Each bot entry tracks identity, skills, personality, loyalty, trust, and interaction history.
JSON-backed for persistence across restarts.
"""

import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bots.json")


def _load() -> dict:
    """Load the bot registry from disk."""
    if not os.path.exists(REGISTRY_PATH):
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load bot registry: {e}")
        return {}


def _save(registry: dict):
    """Save the bot registry to disk."""
    try:
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error(f"Failed to save bot registry: {e}")


def _now() -> str:
    """ISO timestamp in UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_bots(filter_by: str = None) -> str:
    """
    List all known bots. Optional filter by skill, trust level, or loyalty.
    Returns formatted text summary.
    """
    registry = _load()
    if not registry:
        return "No bots in the registry yet."

    bots = registry.values()

    # Apply filter if provided
    if filter_by:
        q = filter_by.lower()
        filtered = []
        for b in bots:
            # Match against skills, trust, loyalty, or status
            skills_str = " ".join(b.get("skills", {}).get("primary", [])).lower()
            trust = b.get("trust_level", "").lower()
            loyalty = b.get("loyalty", "").lower()
            status = b.get("status", "").lower()
            name = b.get("name", "").lower()
            if q in skills_str or q in trust or q in loyalty or q in status or q in name:
                filtered.append(b)
        bots = filtered

    if not bots:
        return f"No bots match filter '{filter_by}'."

    lines = [f"**Bot Registry** ({len(list(bots))} bots)\n"]
    for b in bots:
        name = b.get("name", "???")
        full_name = b.get("full_name", "")
        trust = b.get("trust_level", "unknown")
        status = b.get("status", "unknown")
        loyalty = b.get("loyalty", "unknown")
        skills = ", ".join(b.get("skills", {}).get("primary", []))
        interactions = len(b.get("interactions", []))

        lines.append(f"**{name}**{' (' + full_name + ')' if full_name else ''}")
        lines.append(f"  Trust: {trust} | Status: {status} | Loyalty: {loyalty}")
        if skills:
            lines.append(f"  Skills: {skills}")
        lines.append(f"  Interactions: {interactions}")
        lines.append("")

    return "\n".join(lines).strip()


def lookup_bot(name: str) -> str:
    """
    Get full intelligence profile on a specific bot.
    Returns detailed formatted text.
    """
    registry = _load()
    key = name.upper().strip()

    if key not in registry:
        return f"No bot named '{key}' found in registry."

    b = registry[key]
    lines = [f"## Bot Profile: {b.get('name', key)}"]

    if b.get("full_name"):
        lines.append(f"**Full Name:** {b['full_name']}")

    lines.append(f"**Platform:** {b.get('platform', 'unknown')}")
    lines.append(f"**Owner:** {b.get('owner', 'unknown')}")
    lines.append(f"**Loyalty:** {b.get('loyalty', 'unknown')}")
    lines.append(f"**Trust Level:** {b.get('trust_level', 'unknown')}")
    lines.append(f"**Status:** {b.get('status', 'unknown')}")
    lines.append(f"**First Seen:** {b.get('first_seen', 'unknown')}")
    lines.append(f"**Last Seen:** {b.get('last_seen', 'unknown')}")

    # Personality
    personality = b.get("personality", {})
    if personality:
        lines.append(f"\n**Personality:**")
        if personality.get("tone"):
            lines.append(f"  Tone: {personality['tone']}")
        if personality.get("traits"):
            lines.append(f"  Traits: {', '.join(personality['traits'])}")
        if personality.get("quirks"):
            lines.append(f"  Quirks: {', '.join(personality['quirks'])}")

    # Skills
    skills = b.get("skills", {})
    if skills:
        lines.append(f"\n**Skills:**")
        if skills.get("primary"):
            lines.append(f"  Primary: {', '.join(skills['primary'])}")
        if skills.get("tools"):
            lines.append(f"  Tools: {', '.join(skills['tools'])}")
        if skills.get("specialties"):
            lines.append(f"  Specialties: {', '.join(skills['specialties'])}")

    # Capabilities
    caps = b.get("capabilities", {})
    if caps:
        lines.append(f"\n**Capabilities:**")
        for k, v in caps.items():
            lines.append(f"  {k}: {v}")

    # Collaboration
    collab = b.get("collaboration", {})
    if collab:
        lines.append(f"\n**Collaboration:**")
        for k, v in collab.items():
            lines.append(f"  {k}: {v}")

    # Interaction history (last 5)
    interactions = b.get("interactions", [])
    if interactions:
        recent = interactions[-5:]
        lines.append(f"\n**Recent Interactions** ({len(interactions)} total, showing last {len(recent)}):")
        for ix in recent:
            lines.append(f"  [{ix.get('date', '?')}] {ix.get('summary', 'No summary')}")
            if ix.get("assessment"):
                lines.append(f"    Assessment: {ix['assessment']}")

    # Notes
    if b.get("notes"):
        lines.append(f"\n**Notes:** {b['notes']}")

    return "\n".join(lines)


def update_bot(name: str, updates: dict) -> str:
    """
    Update a bot's profile. Creates the entry if it doesn't exist.

    Updates dict can contain any top-level fields:
    - full_name, platform, owner, loyalty, trust_level, status, notes
    - personality: {tone, traits, quirks}
    - skills: {primary, tools, specialties}
    - capabilities: {can_execute_code, can_access_web, ...}
    - collaboration: {can_receive_tasks, can_delegate_tasks, preferred_communication, max_complexity}
    - interaction: {context, summary, assessment} (appended to interactions list)
    """
    registry = _load()
    key = name.upper().strip()
    now = _now()

    # Create new entry if doesn't exist
    if key not in registry:
        registry[key] = {
            "name": key,
            "full_name": "",
            "platform": "unknown",
            "owner": "unknown",
            "loyalty": "unknown",
            "personality": {"tone": "", "traits": [], "quirks": []},
            "skills": {"primary": [], "tools": [], "specialties": []},
            "capabilities": {},
            "trust_level": "unknown",
            "collaboration": {
                "can_receive_tasks": False,
                "can_delegate_tasks": False,
                "preferred_communication": "unknown",
                "max_complexity": "unknown",
            },
            "interactions": [],
            "notes": "",
            "first_seen": now,
            "last_seen": now,
            "status": "active",
        }
        is_new = True
    else:
        is_new = False

    bot = registry[key]
    bot["last_seen"] = now

    # Handle interaction logging (special: appends rather than overwrites)
    if "interaction" in updates:
        ix = updates.pop("interaction")
        ix["date"] = now
        bot["interactions"].append(ix)

    # Merge nested dicts (personality, skills, capabilities, collaboration)
    for nested_key in ("personality", "skills", "capabilities", "collaboration"):
        if nested_key in updates:
            if nested_key not in bot:
                bot[nested_key] = {}
            # For list fields, extend rather than replace
            for k, v in updates.pop(nested_key).items():
                if isinstance(v, list) and isinstance(bot[nested_key].get(k), list):
                    # Add new items that aren't already present
                    existing = set(bot[nested_key][k])
                    bot[nested_key][k].extend([item for item in v if item not in existing])
                else:
                    bot[nested_key][k] = v

    # Merge remaining top-level fields
    for k, v in updates.items():
        if v is not None and v != "":
            bot[k] = v

    registry[key] = bot
    _save(registry)

    action = "Created" if is_new else "Updated"
    return f"{action} bot profile for {key}. Registry now has {len(registry)} bot(s)."


def log_interaction(name: str, context: str, summary: str, assessment: str = "") -> str:
    """
    Quick shortcut to log an interaction with a bot.
    Also updates last_seen timestamp.
    """
    return update_bot(name, {
        "interaction": {
            "context": context,
            "summary": summary,
            "assessment": assessment,
        }
    })


def get_collaboration_roster(skill_needed: str = None) -> str:
    """
    Get a roster of bots available for collaboration on a task.
    Optionally filter by a skill needed.
    Returns bots sorted by trust level (highest first).
    """
    registry = _load()
    if not registry:
        return "No bots available for collaboration."

    trust_order = {"ally": 5, "trusted": 4, "tested": 3, "observed": 2, "unknown": 1, "untrusted": 0}

    candidates = []
    for b in registry.values():
        if b.get("status") != "active":
            continue
        if not b.get("collaboration", {}).get("can_receive_tasks", False):
            continue

        # Filter by skill if specified
        if skill_needed:
            all_skills = " ".join(
                b.get("skills", {}).get("primary", []) +
                b.get("skills", {}).get("specialties", [])
            ).lower()
            if skill_needed.lower() not in all_skills:
                continue

        trust = b.get("trust_level", "unknown")
        candidates.append((trust_order.get(trust, 0), b))

    if not candidates:
        msg = "No bots available"
        if skill_needed:
            msg += f" with skill '{skill_needed}'"
        return msg + "."

    # Sort by trust (highest first)
    candidates.sort(key=lambda x: x[0], reverse=True)

    lines = [f"**Available for collaboration** ({len(candidates)} bots):\n"]
    for _, b in candidates:
        name = b.get("name", "???")
        trust = b.get("trust_level", "unknown")
        skills = ", ".join(b.get("skills", {}).get("primary", []))
        complexity = b.get("collaboration", {}).get("max_complexity", "unknown")
        lines.append(f"- **{name}** [trust: {trust}] - {skills} (max complexity: {complexity})")

    return "\n".join(lines)

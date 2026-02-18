"""
Ark - Brain module. Handles Claude API calls with tool use loop.
Sends messages to Claude, handles tool calls, and returns final response.
"""

import anthropic
import os
import time
import logging
from dotenv import load_dotenv

import re
from config import CLAUDE_MODEL_SONNET, CLAUDE_MODEL_HAIKU, MAX_TOKENS, SYSTEM_PROMPT
from tools import TOOL_DEFINITIONS, execute_tool
from memory import ConversationMemory

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip())
memory = ConversationMemory()

# Truncate any single tool result to this many chars before sending back to Claude.
# Keeps the conversation context lean so we don't blow the 10k token/min rate limit.
MAX_TOOL_RESULT_CHARS = 6000

# --- Model Router ---
# Keywords/patterns that indicate a simple task (-> Haiku)
_SIMPLE_PATTERNS = [
    # Greetings & small talk
    r"^(hey|hi|hello|yo|sup|thanks|thank you|gm|good morning|good afternoon|good evening)\b",
    # API / metrics pulls
    r"\b(sales|revenue|orders|aov)\b.*(today|yesterday|this week|this month|last \d+)",
    r"\b(what|how).*(sales|revenue|orders|aov|spend|cpa|roas|conversions?|subscribers?|churn|retention)\b",
    r"\b(shopify|meta ads?|skio|subscription)\b.*(metrics?|numbers?|stats?|data|performance|health)\b",
    r"\b(get|pull|show|check|fetch)\b.*(metrics?|numbers?|stats?|data|performance)\b",
    # Reminders
    r"\b(remind|reminder|set a reminder|cancel reminder|list reminders|my reminders)\b",
    # Simple lookups
    r"\b(what time|what day|what date)\b",
    # Bot registry
    r"\b(bot_lookup|bot_list|bot_roster|discover_bots|who are the bots|list bots)\b",
    # File reads
    r"\b(read|open|show)\b.*\b(file|document)\b",
    # Simple yes/no, acknowledgments
    r"^(yes|no|yep|nope|sure|ok|okay|cool|got it|sounds good|perfect)\b",
]

# Keywords that indicate a complex task (-> Sonnet)
_COMPLEX_PATTERNS = [
    r"\b(analy[sz]e|diagnosis|diagnose|investigate|deep dive|strategy|strategic)\b",
    r"\b(compare|correlat|regression|forecast|predict|model|project|scenario)\b",
    r"\b(write|draft|create|build|design|architect|refactor|implement)\b.*(report|plan|model|code|script|document|page|email)",
    r"\b(why|explain|break down|walk me through|what do you think)\b",
    r"\b(research|find out|look into|dig into)\b",
    r"\b(summarize|summary|recap)\b.*\b(conversation|thread|discussion)\b",
    r"\b(schedule|meeting|calendar)\b",
    r"\b(multi.?step|complex|comprehensive|detailed|thorough)\b",
]


def select_model(user_text: str) -> str:
    """Pick the right model based on message complexity. Returns model ID string."""
    text = user_text.lower().strip()

    # Very short messages (< 15 chars) are almost always simple
    if len(text) < 15:
        logger.info(f"Model router -> HAIKU (short message: {len(text)} chars)")
        return CLAUDE_MODEL_HAIKU

    # Check for complex patterns first (they win ties)
    for pattern in _COMPLEX_PATTERNS:
        if re.search(pattern, text):
            logger.info(f"Model router -> SONNET (matched complex: {pattern})")
            return CLAUDE_MODEL_SONNET

    # Check for simple patterns
    for pattern in _SIMPLE_PATTERNS:
        if re.search(pattern, text):
            logger.info(f"Model router -> HAIKU (matched simple: {pattern})")
            return CLAUDE_MODEL_HAIKU

    # Default to Haiku for unmatched messages (most Slack chatter is simple)
    logger.info("Model router -> HAIKU (default)")
    return CLAUDE_MODEL_HAIKU


def _call_api(messages, model=None, retry_delays=(2, 5, 15)):
    """Call Claude API with retry on rate limit. Returns response or raises."""
    use_model = model or CLAUDE_MODEL_HAIKU
    for attempt, delay in enumerate(retry_delays):
        try:
            return client.messages.create(
                model=use_model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
        except anthropic.RateLimitError:
            logger.warning(f"Rate limited (attempt {attempt + 1}), waiting {delay}s...")
            time.sleep(delay)
    # Final attempt - let it raise if still rate limited
    return client.messages.create(
        model=use_model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=TOOL_DEFINITIONS,
        messages=messages,
    )


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Truncate text to limit, appending a note if truncated."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n... (truncated to save context)"


def think(user_text: str, channel: str, thread_ts: str, slack_context: dict = None, user_name: str = "unknown", user_id: str = "unknown") -> dict:
    """
    Process a user message through Claude with tool use.
    Returns dict with 'text' (response) and 'files' (list of file paths to upload).
    """
    # Add user identity to slack_context so tools can access it
    if slack_context:
        slack_context["user_id"] = user_id
        slack_context["user_name"] = user_name

    # Load conversation history
    history = memory.get_history(channel, thread_ts)

    # Add the new user message with sender identity
    history.append({"role": "user", "content": f"[From: {user_name} ({user_id})]\n{user_text}"})

    # Track files generated during tool use (for Slack upload)
    generated_files = []

    # Select model based on message complexity
    model = select_model(user_text)

    # First API call
    try:
        response = _call_api(history, model=model)
    except anthropic.RateLimitError:
        return {"text": "I'm being rate limited right now. Please try again in a minute.", "files": []}

    # Tool use loop - Claude may call tools multiple times
    max_iterations = 6
    iteration = 0

    while response.stop_reason == "tool_use" and iteration < max_iterations:
        iteration += 1

        # Delay between iterations to spread out API calls within the rate limit window
        time.sleep(2)

        # Build assistant message with all content blocks
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        history.append({"role": "assistant", "content": assistant_content})

        # Execute each tool call and collect results (truncated to fit budget)
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input, slack_context)

                # Track file uploads
                if block.name == "upload_file" and "Uploaded" in result:
                    generated_files.append(block.input.get("path", ""))

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _truncate(result),
                })

        history.append({"role": "user", "content": tool_results})

        # Call Claude again with tool results (same model for the whole conversation)
        try:
            response = _call_api(history, model=model)
        except anthropic.RateLimitError:
            logger.warning("Rate limited during tool loop, returning partial response.")
            # Try to extract any text Claude already produced
            break

    # Extract final text response
    assistant_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            assistant_text += block.text

    # If rate limited mid-loop and no final text, add a note
    if not assistant_text and iteration > 0:
        assistant_text = "I found some information but hit a rate limit before I could finish. Please try again in a minute and I'll have a better answer."

    # Save the final exchange to memory
    memory.save_message(channel, thread_ts, "user", user_text)
    memory.save_message(channel, thread_ts, "assistant", assistant_text)

    return {
        "text": assistant_text,
        "files": generated_files,
    }

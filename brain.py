"""
Ark - Brain module. Handles Claude API calls with tool use loop.
Sends messages to Claude, handles tool calls, and returns final response.
"""

import anthropic
import os
import time
from dotenv import load_dotenv

from config import CLAUDE_MODEL, MAX_TOKENS, SYSTEM_PROMPT
from tools import TOOL_DEFINITIONS, execute_tool
from memory import ConversationMemory

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip())
memory = ConversationMemory()


def think(user_text: str, channel: str, thread_ts: str, slack_context: dict = None) -> dict:
    """
    Process a user message through Claude with tool use.
    Returns dict with 'text' (response) and 'files' (list of file paths to upload).
    """
    # Load conversation history
    history = memory.get_history(channel, thread_ts)

    # Add the new user message
    history.append({"role": "user", "content": user_text})

    # Track files generated during tool use (for Slack upload)
    generated_files = []

    # Call Claude API
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=TOOL_DEFINITIONS,
        messages=history,
    )

    # Tool use loop - Claude may call tools multiple times
    max_iterations = 5  # Safety limit to prevent runaway API calls
    iteration = 0

    while response.stop_reason == "tool_use" and iteration < max_iterations:
        iteration += 1

        # Small delay between iterations to avoid rate limits
        if iteration > 1:
            time.sleep(1)

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

        # Execute each tool call and collect results
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
                    "content": result,
                })

        history.append({"role": "user", "content": tool_results})

        # Call Claude again with tool results
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=history,
        )

    # Extract final text response
    assistant_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            assistant_text += block.text

    # Save the final exchange to memory
    memory.save_message(channel, thread_ts, "user", user_text)
    memory.save_message(channel, thread_ts, "assistant", assistant_text)

    return {
        "text": assistant_text,
        "files": generated_files,
    }

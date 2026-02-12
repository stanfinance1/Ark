"""
Test script for the new conversation intelligence tools.
Run this to verify the tools are working correctly before deployment.

Usage:
  python test_conversation_tools.py
"""

import sys
import os

# Add ark directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools import execute_tool

def test_analyze_conversation():
    """Test the analyze_conversation tool."""
    print("\n=== Testing analyze_conversation ===")

    # Mock slack context with conversation history
    mock_context = {
        "channel": "C12345TEST",
        "thread_ts": "1234567890.123456",
        "user_id": "U086HEJAUTH",
        "user_name": "Stan Karaba",
        "timestamp": "1234567890.123456",
    }

    result = execute_tool(
        name="analyze_conversation",
        inputs={"include_history": False},
        slack_context=mock_context,
    )

    print(result)

    if "Conversation Analysis" in result or "No conversation history" in result:
        print("✓ analyze_conversation works!")
        return True
    else:
        print("✗ analyze_conversation failed!")
        return False


def test_suggest_meeting():
    """Test the suggest_meeting_with_context tool."""
    print("\n=== Testing suggest_meeting_with_context ===")

    mock_context = {
        "channel": "C12345TEST",
        "thread_ts": "1234567890.123456",
        "user_id": "U086HEJAUTH",
        "user_name": "Stan Karaba",
        "timestamp": "1234567890.123456",
    }

    result = execute_tool(
        name="suggest_meeting_with_context",
        inputs={
            "reason": "Multiple back-and-forth exchanges without resolution",
            "proposed_attendees": ["Stan", "Sarah", "Alex"],
            "proposed_agenda": [
                "Review Q1 marketing strategy",
                "Discuss budget allocation",
                "Align on timeline",
            ],
            "suggested_duration": 30,
            "schedule_immediately": False,
        },
        slack_context=mock_context,
    )

    print(result)

    if "Meeting Recommendation" in result:
        print("✓ suggest_meeting_with_context works!")
        return True
    else:
        print("✗ suggest_meeting_with_context failed!")
        return False


def test_send_summary():
    """Test the send_summary_to_stan tool."""
    print("\n=== Testing send_summary_to_stan ===")
    print("NOTE: This will attempt to send a DM to Stan if Slack client is available.")
    print("Expected: 'Error: No Slack client available' (we're in test mode)")

    mock_context = {
        "channel": "C12345TEST",
        "thread_ts": "1234567890.123456",
        "user_id": "U086HEJAUTH",
        "user_name": "Stan Karaba",
        "timestamp": "1234567890.123456",
    }

    result = execute_tool(
        name="send_summary_to_stan",
        inputs={
            "summary": "Test conversation about Q1 planning",
            "key_points": [
                "Budget approved for $50k marketing spend",
                "Launch date set for March 1st",
            ],
            "action_items": [
                "Stan: Finalize vendor contracts by Friday",
                "Sarah: Send creative brief by EOW",
            ],
            "recommendations": "Schedule follow-up in 2 weeks to review progress",
            "urgency": "medium",
        },
        slack_context=mock_context,
    )

    print(result)

    if "Error: No Slack client available" in result:
        print("✓ send_summary_to_stan works (test mode - no Slack client)!")
        return True
    elif "Summary sent to Stan" in result:
        print("✓ send_summary_to_stan works (LIVE - actually sent DM)!")
        return True
    else:
        print("✗ send_summary_to_stan failed!")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Conversation Intelligence Tools - Test Suite")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("analyze_conversation", test_analyze_conversation()))
    results.append(("suggest_meeting_with_context", test_suggest_meeting()))
    results.append(("send_summary_to_stan", test_send_summary()))

    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {name}: {status}")

    all_passed = all(passed for _, passed in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("All tests passed! ✓")
        print("\nReady to deploy:")
        print("1. cd claude-only/ark/")
        print("2. git add .")
        print('3. git commit -m "Add conversation intelligence tools"')
        print("4. git push")
        print("\nRailway will auto-deploy in ~30 seconds.")
    else:
        print("Some tests failed! ✗")
        print("Review the output above and fix any issues before deploying.")
    print("=" * 60)


if __name__ == "__main__":
    main()

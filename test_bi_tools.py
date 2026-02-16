"""
Quick test of the new Business Intelligence tools for Ark.
Tests Shopify, Meta Ads, and SKIO API integrations.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools import execute_tool

def test_shopify():
    print("="*60)
    print("TESTING SHOPIFY METRICS")
    print("="*60)
    result = execute_tool("get_shopify_metrics", {"timeframe": "today"})
    print(result)
    print()

def test_meta_ads():
    print("="*60)
    print("TESTING META ADS PERFORMANCE")
    print("="*60)
    result = execute_tool("get_meta_ads_performance", {"timeframe": "last_7d"})
    print(result)
    print()

def test_skio():
    print("="*60)
    print("TESTING SKIO SUBSCRIPTION HEALTH")
    print("="*60)
    result = execute_tool("get_skio_health", {"include_churn_risk": False})
    print(result)
    print()

if __name__ == "__main__":
    print("\nTesting Ark Business Intelligence Tools\n")

    # Test each tool
    try:
        test_shopify()
    except Exception as e:
        print(f"Shopify test failed: {e}\n")

    try:
        test_meta_ads()
    except Exception as e:
        print(f"Meta Ads test failed: {e}\n")

    try:
        test_skio()
    except Exception as e:
        print(f"SKIO test failed: {e}\n")

    print("\nAll tests complete!")

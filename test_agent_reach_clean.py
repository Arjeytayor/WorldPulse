"""Test script to verify agent_reach module works correctly.

Run this to test all deep-dive sources after making changes to agent_reach.py.
Usage: python test_agent_reach_clean.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_reach import (
    fetch_twitter,
    fetch_reddit,
    fetch_youtube_transcript,
    fetch_web_page,
    deep_dive,
)


def print_header(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def test_twitter():
    print_header("TWITTER / X - Searching for 'Bitcoin'")
    tweets = fetch_twitter("Bitcoin", limit=5)
    print(f"Retrieved: {len(tweets)} tweets")
    for i, tweet in enumerate(tweets[:3], 1):
        # Strip emojis and non-ASCII for Windows console safety
        safe = tweet.encode("ascii", "ignore").decode()[:100]
        print(f"  {i}. {safe}...")


def test_reddit():
    print_header("REDDIT - Searching r/Bitcoin")
    posts = fetch_reddit("Bitcoin", subreddit="Bitcoin", limit=5)
    print(f"Retrieved: {len(posts)} posts")
    for i, post in enumerate(posts[:3], 1):
        title = post.get("title", "no title").encode("ascii", "ignore").decode()[:80]
        upvotes = post.get("upvotes", "?")
        print(f"  {i}. [{upvotes} U] {title}")


def test_youtube():
    print_header("YOUTUBE - Fetching transcript")
    # Test URLs (use a known educational video)
    test_videos = [
        "https://www.youtube.com/watch?v=bBC-nXUjYaI",  # TED talk - short and popular
    ]
    for vid_url in test_videos:
        try:
            transcript = fetch_youtube_transcript(vid_url)
            if transcript:
                print(f"Transcript: {len(transcript)} chars")
                safe = transcript.encode("ascii", "ignore").decode()[:150]
                print(f"  Preview: {safe}...")
                return
        except Exception as exc:
            print(f"  Warning: {exc}")
    print("  Could not fetch transcript.")


def test_web():
    print_header("WEB - Fetching via Jina Reader")
    content = fetch_web_page("https://www.coindesk.com/markets/")
    if content:
        print(f"Content: {len(content)} chars")
        safe = content.encode("ascii", "ignore").decode()[:150]
        print(f"  Preview: {safe}...")
    else:
        print("  Could not fetch content.")


def test_deep_dive():
    print_header("DEEP DIVE - Full orchestrator test")
    mock_brief = {
        "top_query": "Bitcoin price ETF inflows",
        "synthesis": "Bitcoin price surged as ETF inflows reached record levels.",
        "youtube": [{"url": "https://www.youtube.com/watch?v=bBC-nXUjYaI"}],
    }
    result = deep_dive("Bitcoin ETF inflows", mock_brief)
    print(f"Results:")
    print(f"  Tweets: {len(result.get('tweets', []))}")
    print(f"  Reddit posts: {len(result.get('reddit_posts', []))}")
    print(f"  YouTube transcript: {'Found' if result.get('youtube_transcript') else 'Not found'}")
    tweets = result.get("tweets", [])
    if tweets:
        safe = tweets[0].encode("ascii", "ignore").decode()[:80]
        print(f"  Sample tweet: {safe}...")


if __name__ == "__main__":
    print("=" * 60)
    print("  AFRICAN PULSE - Agent-Reach Test Suite")
    print("=" * 60)

    test_twitter()
    test_reddit()
    test_youtube()
    test_web()
    test_deep_dive()

    print("\n" + "=" * 60)
    print("  ALL TESTS COMPLETE")
    print("=" * 60)
    print("  Check logs/errors.log for detailed output")

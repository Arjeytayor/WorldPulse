"""Agent-Reach wrapper -- real CLI first, unbreakable fallbacks.

Hierarchy for every source:
  1. Real CLI tool (installed by agent-reach installer)
  2. HTTP API (free, no auth, fast)
  3. HTML scraping (last resort, best-effort)
  4. Return [] / "" with a warning (never crash the pipeline)

The native `agent-reach` install command sets up the individual CLIs.
We call those directly so you get all their features (rate-limit handling,
proxy rotation, headless browsers, etc.)

If a CLI is missing or fails, we transparently fall back to methods that
work anywhere without extra binaries.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import date
from typing import Final

import requests

from logger import logger
from config import DEEP_DIVE_CACHE_DIR

# ── Constants ─────────────────────────────────────────────

CACHE_DIR = DEEP_DIVE_CACHE_DIR
REDDIT_JSON: Final[str] = "https://www.reddit.com/{endpoint}.json"
NITTER_INSTANCES: Final[list[str]] = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.cz",
]
JINA_READER: Final[str] = "https://r.jina.ai/{url}"

os.makedirs(CACHE_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════

def _cache_path(key: str, day: str | None = None) -> str:
    today = day or date.today().isoformat()
    safe = re.sub(r"[^a-z0-9_]", "_", key.lower())[:60]
    return os.path.join(CACHE_DIR, f"{safe}_{today}.json")


def _load_cache(key: str) -> dict | None:
    path = _cache_path(key)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.debug(f"Cache hit for {key}")
                return data
        except Exception:
            pass
    return None


def _save_cache(key: str, data: dict) -> None:
    try:
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        logger.warning(f"Could not write cache for {key}")


def _which(cmd: str) -> bool:
    """Return True if *cmd* is on PATH (cross-platform)."""
    return shutil.which(cmd) is not None


def _run(cmd: list[str], timeout: int = 30) -> str:
    """Run a subprocess, return stdout string. Raises on non-zero exit."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or f"{' '.join(cmd)} exited {result.returncode}")
    return result.stdout


# ═══════════════════════════════════════════════════════════
#  Twitter / X
# ═══════════════════════════════════════════════════════════

def fetch_twitter(query: str, limit: int = 10) -> list[str]:
    """Search Twitter/X via real CLI -> JSON API -> Nitter scrape."""
    cache_key = f"twitter_{query}_{limit}"
    cached = _load_cache(cache_key)
    if cached:
        return cached.get("tweets", [])

    tweets: list[str] = []
    source = "unknown"

    # ---- Tier 1: real twitter-CLI (installed by agent-reach) ----------
    # Correct syntax: -n (or --max) for count, --json for JSON output
    if _which("twitter"):
        try:
            stdout = _run(["twitter", "search", query, "-n", str(limit), "--json"], timeout=30)
            cli_data = json.loads(stdout)
            # Parse the rich JSON -- extract tweet texts
            if cli_data.get("ok") and "data" in cli_data:
                for tweet in cli_data["data"]:
                    if isinstance(tweet, dict) and tweet.get("text"):
                        tweets.append(tweet["text"])
                if tweets:
                    source = "twitter-cli"
                    logger.info(f"Twitter CLI returned {len(tweets)} tweets for '{query}'")
        except json.JSONDecodeError as exc:
            logger.debug(f"twitter CLI returned non-JSON: {exc}")
        except Exception as exc:
            logger.debug(f"twitter CLI failed: {exc}")

    # ---- Tier 2: free JSON proxies (no auth, fast) ------------------
    if not tweets:
        try:
            tweets = _twitter_json_api(query, limit)
            if tweets:
                source = "twitter-json-proxy"
                logger.info(f"Twitter JSON proxy returned {len(tweets)} tweets for '{query}'")
        except Exception as exc:
            logger.debug(f"Twitter JSON proxy failed: {exc}")

    # ---- Tier 3: Nitter HTML scraping (best-effort) ------------------
    if not tweets:
        try:
            tweets = _nitter_scrape(query, limit)
            if tweets:
                source = "nitter"
                logger.info(f"Nitter returned {len(tweets)} tweets for '{query}'")
        except Exception as exc:
            logger.debug(f"Nitter scrape failed: {exc}")

    # ---- Persist ----------------------------------------------------
    if tweets:
        _save_cache(cache_key, {"tweets": tweets, "source": source})
    else:
        logger.warning(f"All Twitter methods failed for '{query}' -- returning empty list")

    return tweets


def _twitter_json_api(query: str, limit: int) -> list[str]:
    """Free Twitter JSON search via nitter instances."""
    # Nitter exposes a /search timeline with ?f=tweets&q=...
    tweets: list[str] = []
    for base in NITTER_INSTANCES:
        try:
            url = f"{base}/search?f=tweets&q={requests.utils.quote(query)}"
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            text = re.sub(r"<[^>]+>", " ", r.text)
            # Extract likely tweet body lines (heuristic: length > 20, < 300)
            candidates = [ln.strip() for ln in text.splitlines() if 20 < len(ln.strip()) < 300]
            tweets = candidates[:limit]
            if tweets:
                break
        except Exception:
            continue
    return tweets


def _nitter_scrape(query: str, limit: int) -> list[str]:
    """Best-effort Nitter HTML scrape."""
    tweets: list[str] = []
    for base in NITTER_INSTANCES:
        try:
            url = f"{base}/search?f=tweets&q={requests.utils.quote(query)}"
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            # Look for common tweet-content containers
            matches = re.findall(
                r'<div class="tweet-content[^"]*">(.*?)</div>', r.text, re.DOTALL
            )
            for m in matches[:limit]:
                clean = re.sub(r"<[^>]+>", "", m).strip()
                if clean and len(clean) > 10:
                    tweets.append(clean)
            if tweets:
                break
        except Exception:
            continue
    return tweets


# ═══════════════════════════════════════════════════════════
#  Reddit
# ═══════════════════════════════════════════════════════════

def fetch_reddit(query: str, subreddit: str = "", limit: int = 5) -> list[dict]:
    """Search Reddit via real CLI -> JSON API."""
    cache_key = f"reddit_{query}_{subreddit}_{limit}"
    cached = _load_cache(cache_key)
    if cached:
        return cached.get("posts", [])

    posts: list[dict] = []
    source = "unknown"

    # ---- Tier 1: real rdt-cli (installed by agent-reach) --------
    # NOTE: rdt requires auth. If unauthenticated, it will fail
    # and the system will fall back to Tier 2 automatically.
    if _which("rdt"):
        try:
            cmd = ["rdt", "search", query, "--max", str(limit)]
            if subreddit:
                cmd += ["--subreddit", subreddit]
            stdout = _run(cmd, timeout=30)
            # rdt-cli may output JSON lines
            lines = [ln for ln in stdout.splitlines() if ln.strip()]
            for line in lines:
                try:
                    posts.append(json.loads(line))
                except json.JSONDecodeError:
                    posts.append({"title": line.strip(), "body": "", "upvotes": 0})
            if posts:
                source = "rdt-cli"
                logger.info(f"rdt-cli returned {len(posts)} posts for '{query}'")
        except Exception as exc:
            logger.debug(f"rdt CLI failed (may need auth): {exc}")

    # ---- Tier 2: Reddit JSON API (public, no auth) ------------------
    if not posts:
        try:
            posts = _reddit_json_search(query, subreddit, limit)
            if posts:
                source = "reddit-json-api"
                logger.info(f"Reddit JSON API returned {len(posts)} posts for '{query}'")
        except Exception as exc:
            logger.debug(f"Reddit JSON API failed: {exc}")

    # ---- Persist ----------------------------------------------------
    if posts:
        _save_cache(cache_key, {"posts": posts, "source": source})
    else:
        logger.warning(f"All Reddit methods failed for '{query}' -- returning empty list")

    return posts


def _reddit_json_search(query: str, subreddit: str, limit: int) -> list[dict]:
    endpoint = f"r/{subreddit}/search" if subreddit else "search"
    url = (
        f"https://www.reddit.com/{endpoint}.json"
        f"?q={requests.utils.quote(query)}"
        f"&limit={limit}&sort=hot&t=week"
    )
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    posts = []
    for child in data.get("data", {}).get("children", [])[:limit]:
        p = child.get("data", {})
        posts.append({
            "title": p.get("title", ""),
            "body": p.get("selftext", "")[:500],
            "upvotes": p.get("ups", 0),
            "url": f"https://reddit.com{p.get('permalink', '')}",
        })
    return posts


# ═══════════════════════════════════════════════════════════
#  YouTube
# ═══════════════════════════════════════════════════════════

def fetch_youtube_transcript(url: str) -> str:
    """Extract transcript via yt-dlp -> youtube-transcript-api -> captions."""
    video_id = _extract_youtube_id(url)
    cache_key = f"yt_{video_id}"
    cached = _load_cache(cache_key)
    if cached:
        return cached.get("transcript", "")

    transcript = ""
    source = "unknown"

    # ---- Tier 1: yt-dlp (installed by agent-reach) ------------------
    if _which("yt-dlp"):
        try:
            # Use yt-dlp to list available subtitles first
            tmp_dir = os.environ.get("TMP", os.path.dirname(__file__))
            tmp = os.path.join(tmp_dir, f"yt_sub_{video_id}")
            # Try auto-generated English subtitles first, then regular
            _run(
                [
                    "yt-dlp",
                    "--write-auto-sub",
                    "--sub-langs", "en",
                    "--skip-download",
                    "--sub-format", "vtt",
                    "--output", tmp,
                    url,
                ],
                timeout=60,
            )
            # yt-dlp writes files like: tmp.en.vtt, tmp.en-US.vtt
            vtt_candidates = [
                f"{tmp}.en.vtt",
                f"{tmp}.en-US.vtt",
                f"{tmp}.en-GB.vtt",
            ]
            for vtt_path in vtt_candidates:
                if os.path.exists(vtt_path):
                    with open(vtt_path, "r", encoding="utf-8") as f:
                        raw = f.read()
                    lines = [
                        ln.strip() for ln in raw.splitlines()
                        if ln.strip() and "-->" not in ln and not ln.startswith("WEBVTT")
                    ]
                    transcript = " ".join(lines)
                    source = "yt-dlp"
                    logger.info(f"yt-dlp returned transcript ({len(transcript)} chars) for {url}")
                    break
        except Exception as exc:
            logger.debug(f"yt-dlp failed: {exc}")

    # ---- Tier 2: youtube-transcript-api (pip installable) --------
    if not transcript:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            transcript = " ".join(seg["text"] for seg in transcript_list)
            source = "youtube-transcript-api"
            logger.info(f"youtube-transcript-api returned transcript ({len(transcript)} chars)")
        except Exception as exc:
            logger.debug(f"youtube-transcript-api failed: {exc}")

    # ---- Tier 3: captions from third-party fetch --------------------
    if not transcript:
        try:
            transcript = _youtube_caption_scrape(video_id)
            if transcript:
                source = "youtube-caption-scrape"
                logger.info(f"Caption scrape returned {len(transcript)} chars for {video_id}")
        except Exception as exc:
            logger.debug(f"YouTube caption scrape failed: {exc}")

    # ---- Persist ----------------------------------------------------
    if transcript:
        _save_cache(cache_key, {"transcript": transcript, "source": source})
    else:
        logger.warning(f"All YouTube methods failed for '{url}' -- returning empty string")

    return transcript


def _extract_youtube_id(url: str) -> str:
    """Extract 11-char video ID from any YouTube URL."""
    patterns = [
        r"(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    # Fallback: last 11 chars
    return url[-11:] if len(url) >= 11 else url


def _youtube_caption_scrape(video_id: str) -> str:
    """Best-effort: fetch video page and look for caption tracks."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        # Look for caption track URLs in the page source
        matches = re.findall(r'"captionTracks":\s*(\[.*?\])', r.text)
        if matches:
            # Try to fetch first caption track
            caption_data = json.loads(matches[0])
            if caption_data:
                caption_url = caption_data[0].get("baseUrl", "")
                if caption_url:
                    cr = requests.get(caption_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    cr.raise_for_status()
                    # Simple XML strip
                    text = re.sub(r"<[^>]+>", " ", cr.text)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════
#  Web fetch
# ═══════════════════════════════════════════════════════════

def fetch_web_page(url: str) -> str:
    """Fetch clean markdown via Jina (agent-reach default) -> raw fetch."""
    cache_key = f"web_{url[-40:]}"
    cached = _load_cache(cache_key)
    if cached:
        return cached.get("content", "")

    content = ""
    source = "unknown"

    # ---- Tier 1: Jina Reader (what agent-reach uses by default) ----
    try:
        jina_url = f"https://r.jina.ai/{url}"
        r = requests.get(jina_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        content = r.text.strip()
        if content:
            source = "jina"
            logger.info(f"Jina Reader returned {len(content)} chars for {url}")
    except Exception as exc:
        logger.debug(f"Jina Reader failed: {exc}")

    # ---- Tier 2: raw fetch + HTML strip -----------------------------
    if not content:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            text = re.sub(r"<[^>]+>", " ", r.text)
            content = re.sub(r"\s+", " ", text).strip()
            source = "raw-html"
            logger.info(f"Raw fetch returned {len(content)} chars for {url}")
        except Exception as exc:
            logger.debug(f"Raw fetch failed: {exc}")

    # ---- Persist ----------------------------------------------------
    if content:
        _save_cache(cache_key, {"content": content, "source": source})
    else:
        logger.warning(f"All web fetch methods failed for '{url}' -- returning empty string")

    return content


# ═══════════════════════════════════════════════════════════
#  Deep-dive orchestrator
# ═══════════════════════════════════════════════════════════

def _pick_subreddit(topic: str) -> str:
    topic_lower = topic.lower()
    if any(w in topic_lower for w in ["defi", "ethereum", "protocol"]):
        return "defi"
    if any(w in topic_lower for w in ["bitcoin", "btc"]):
        return "Bitcoin"
    if any(w in topic_lower for w in ["fed", "interest rates", "inflation", "macro", "debt", "sovereign"]):
        return "economics"
    if any(w in topic_lower for w in ["fintech", "banking", "remittances", "liquidity", "digital banking"]):
        return "stocks"
    return "CryptoCurrency"


def deep_dive(topic: str, brief: dict) -> dict:
    """
    Pull raw source material using Agent-Reach (CLI or HTTP fallback).
    Returns dict with keys: tweets, reddit_posts, youtube_transcript.
    """
    search_query = brief.get("top_query") or brief.get("synthesis", "")[:60] or topic

    tweets = fetch_twitter(search_query, limit=8)
    reddit_posts = fetch_reddit(search_query, subreddit=_pick_subreddit(topic), limit=4)
    youtube_transcript = ""
    # ``brief["youtube"]`` is always *present* but every real producer sets it
    # to [] (news_client.py:106, research.py:42) -- nothing populates it yet.
    # A ``.get(key, default)`` default never fires for a key that exists, so
    # the old ``[{}]`` fallback was dead code and this indexed an empty list on
    # every real deep dive. Only the test fixtures supplied a non-empty list,
    # which is why the tests passed while production raised IndexError.
    videos = brief.get("youtube") or []
    top_video = videos[0].get("url", "") if videos else ""
    if top_video:
        youtube_transcript = fetch_youtube_transcript(top_video)

    return {
        "tweets": tweets,
        "reddit_posts": reddit_posts,
        "youtube_transcript": youtube_transcript,
    }

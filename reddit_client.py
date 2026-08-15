"""Reddit OAuth client — app-only read access.

Reddit blocks unauthenticated requests to the public ``.json`` endpoints with
403, which silently removed every Reddit source from the pipeline. This module
obtains an app-only bearer token from a registered "script" app and talks to
``oauth.reddit.com`` instead.

Configuration (see .env.example):
    REDDIT_CLIENT_ID       from https://www.reddit.com/prefs/apps
    REDDIT_CLIENT_SECRET
    REDDIT_USER_AGENT      optional; Reddit wants a descriptive UA

If credentials are absent, :func:`is_configured` returns False and callers skip
Reddit rather than failing — the pipeline still runs on Google News alone.

Usage:
    from reddit_client import is_configured, get
    data = get("/r/finance/hot", {"limit": 20})
"""

from __future__ import annotations

import threading
import time

import requests

import config
from logger import logger

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"

_lock = threading.Lock()
_token: str | None = None
_token_expires_at: float = 0.0

# Refresh this many seconds before actual expiry, so a long pipeline run can't
# have a token die mid-request.
_EXPIRY_MARGIN = 300.0


def is_configured() -> bool:
    """True when both OAuth credentials are present."""
    return bool(config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET)


def _fetch_token() -> str | None:
    """Request a fresh app-only bearer token. Returns None on failure."""
    try:
        resp = requests.post(
            TOKEN_URL,
            auth=(config.REDDIT_CLIENT_ID, config.REDDIT_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": config.REDDIT_USER_AGENT},
            timeout=15,
        )
        if resp.status_code == 401:
            logger.error(
                "Reddit OAuth rejected the credentials (401). Check "
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET, and that the app "
                "type is 'script'."
            )
            return None
        resp.raise_for_status()
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            logger.error(f"Reddit OAuth returned no access_token: {payload}")
            return None

        global _token_expires_at
        _token_expires_at = time.time() + float(payload.get("expires_in", 3600))
        logger.info("Reddit OAuth token acquired")
        return token
    except Exception:
        logger.error("Reddit OAuth token request failed", exc_info=True)
        return None


def _get_token(*, force: bool = False) -> str | None:
    """Return a valid bearer token, refreshing when expired."""
    global _token
    with _lock:
        if force or not _token or time.time() >= (_token_expires_at - _EXPIRY_MARGIN):
            _token = _fetch_token()
        return _token


def get(path: str, params: dict | None = None) -> dict | None:
    """GET an oauth.reddit.com *path* (e.g. "/r/finance/hot").

    Returns the decoded JSON, or None if Reddit is unconfigured or the request
    failed. Never raises — Reddit is a supplementary source and must not take
    the pipeline down with it.
    """
    if not is_configured():
        return None

    token = _get_token()
    if not token:
        return None

    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"bearer {token}",
        "User-Agent": config.REDDIT_USER_AGENT,
    }

    try:
        resp = requests.get(url, headers=headers, params=params or {}, timeout=15)

        # A token can be revoked server-side before its stated expiry; retry
        # once with a forced refresh before giving up.
        if resp.status_code == 401:
            logger.warning("Reddit returned 401 — refreshing token and retrying once")
            token = _get_token(force=True)
            if not token:
                return None
            headers["Authorization"] = f"bearer {token}"
            resp = requests.get(url, headers=headers, params=params or {}, timeout=15)

        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.warning(f"Reddit request failed: {path}", exc_info=True)
        return None


# ── RSS fallback ──────────────────────────────────────────
#
# Reddit's Atom feeds remain available without authentication, unlike the .json
# endpoints. They are the only free path left for reading public Reddit content
# now that app registration is gated behind manual approval. Two limits matter:
# they carry NO score/upvote field, and they rate-limit aggressively (rapid
# requests return 429), hence the throttle below.

RSS_BASE = "https://www.reddit.com"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Reddit throttles these feeds to roughly 10 requests/minute for unauthenticated
# clients. Measured: 2.5s spacing lost a third of requests; 6s spacing (=10/min,
# exactly at the ceiling) produced a perfectly alternating pass/fail pattern.
# 12s is ~5/min, comfortably inside the limit and a polite rate for a daily job.
# Aggressive retries are counterproductive here -- each one spends the same
# budget the next feed needs -- so there is a single long backoff.
_MIN_RSS_INTERVAL = 12.0
_RSS_BACKOFFS = (30.0,)

_rss_lock = threading.Lock()
_last_rss_call: float = 0.0


def get_rss(path: str) -> list[dict]:
    """Fetch a Reddit Atom feed (e.g. "/r/finance/hot/.rss").

    Returns a list of {"title", "link", "author"}. Never raises. Upvotes are
    not available from RSS, so callers must not filter on them.
    """
    from xml.etree import ElementTree

    global _last_rss_call
    with _rss_lock:
        elapsed = time.time() - _last_rss_call
        if elapsed < _MIN_RSS_INTERVAL:
            time.sleep(_MIN_RSS_INTERVAL - elapsed)
        _last_rss_call = time.time()

    url = f"{RSS_BASE}{path}"
    headers = {"User-Agent": config.REDDIT_USER_AGENT}

    try:
        resp = requests.get(url, headers=headers, timeout=20)

        for backoff in _RSS_BACKOFFS:
            if resp.status_code != 429:
                break
            logger.info(f"Reddit RSS 429 on {path} — backing off {backoff}s")
            time.sleep(backoff)
            with _rss_lock:
                _last_rss_call = time.time()
            resp = requests.get(url, headers=headers, timeout=20)

        if resp.status_code == 429:
            logger.warning(f"Reddit RSS still 429 after retries: {path} — skipping")
            return []

        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)

        entries = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            title = (entry.findtext("atom:title", "", _ATOM_NS) or "").strip()
            if not title:
                continue
            link_el = entry.find("atom:link", _ATOM_NS)
            author = entry.findtext("atom:author/atom:name", "", _ATOM_NS) or ""
            entries.append({
                "title": title,
                "link": link_el.get("href", "") if link_el is not None else "",
                "author": author.strip(),
            })
        return entries
    except Exception:
        logger.warning(f"Reddit RSS failed: {path}", exc_info=True)
        return []


def health_check() -> str:
    """One-line status string, for setup verification."""
    if not is_configured():
        return "NOT CONFIGURED — REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET missing from .env"
    data = get("/r/finance/hot", {"limit": 1})
    if data is None:
        return "FAIL — credentials present but the request did not succeed (see logs)"
    n = len(data.get("data", {}).get("children", []))
    return f"OK — authenticated, /r/finance/hot returned {n} post(s)"

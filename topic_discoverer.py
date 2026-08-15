"""Dynamic topic discovery — replaces hardcoded DAILY_TOPICS.

Fetches trending headlines from Google News RSS and Reddit hot feeds,
then extracts clean topic strings that the research pipeline can consume.

Usage:
    from topic_discoverer import discover_topics
    topics = discover_topics(count=15)
    # topics -> ["Bitcoin price action ETF flows", ...]
"""

from __future__ import annotations

import re
from typing import Final

import requests
from logger import logger

# ── Source configurations ─────────────────────────────────

# Subreddits to scan for hot posts (finance / macro / crypto focus)
REDDIT_SUBREDDITS: Final[list[str]] = [
    "worldnews",
    "finance",
    "cryptocurrency",
    "economy",
    "wallstreetbets",
    "technology",
    "Bitcoin",
    "ethereum",
    "stocks",
    "investing",
]

# Google News RSS endpoints (no auth)
GOOGLE_NEWS_FEEDS: Final[list[str]] = [
    "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en",  # Top stories
    "https://news.google.com/rss/search?q=business+finance+markets&hl=en-GB&gl=GB&ceid=GB:en",
    "https://news.google.com/rss/search?q=crypto+bitcoin+ethereum&hl=en-GB&gl=GB&ceid=GB:en",
]

# Keywords that flag a headline as finance / macro / crypto relevant
# Used for filtering and topic extraction
KEYWORD_CATEGORIES: Final[dict[str, list[str]]] = {
    "crypto": [
        "bitcoin", "ethereum", "crypto", "blockchain", "defi", "stablecoin",
        "halving", "btc", "eth", "altcoin", "mining", "nft", "defi",
        "uniswap", "aave", "staking", "token", "wallet", "exchange",
        "binance", "coinbase", "coin",
    ],
    "macro": [
        "fed", "federal reserve", "interest rate", "inflation", "cpi",
        "gdp", "recession", "stimulus", "unemployment", "jobs", "nfp",
        "treasury", "bond", "yield", "dollar", "usd", "cbdc",
        "fiscal", "monetary", "central bank",
    ],
    "markets": [
        "stock", "market", "equity", "trading", "etf", "index",
        "dow", "nasdaq", "sp500", "s&p", "rally", "crash", "bull",
        "bear", "volatility", "rebalance", "outflows", "inflows",
        "commodity", "oil", "gold", "copper", "lithium",
    ],
    "geopolitics": [
        "trade war", "tariff", "sanction", "conflict", "war",
        "election", "government", "policy", "regulation", "legislation",
        "brexit", "brics", "opec", "diplomatic",
    ],
    "emerging": [
        "emerging market", "brazil", "mexico", "turkey", "nigeria",
        "south africa", "india", "china", "indonesia", "argentina",
        "naira", "rand", "peso", "real", "rupee", "yuan", "won",
    ],
}
ALL_KEYWORDS: Final[set[str]] = {
    kw.lower()
    for lst in KEYWORD_CATEGORIES.values()
    for kw in lst
}

# Noise phrases to strip from headlines
NOISE_PATTERNS: Final[list[str]] = [
    r"\s*-\s*(Reuters|Bloomberg|WSJ|FT|BBC|CNBC|CNN|Al Jazeera|AP|AFP|CoinDesk|CoinTelegraph|Binance|Decrypt|CryptoSlate|Fox Business|Investopedia|MarketWatch)\s*$",
    r"\s*-\s*[\w]+\.[\w]+\s*$",  # catch "- group.bnpparibas", "- news.bloomberg.com" etc.
    r"\s*\|[^|]+Publication\s*$",  # "Headline | Publication" — only at end
    r"\s*-\s*\d+\s*(hours?|days?|minutes?) ago",
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
    r"\d{1,2}:\d{2}\s*(AM|PM)",
    r"\b(opens? in new tab|exclusive|breaking|update)\b",
    r"\$\d+\s*(billion|million|bn|mn)",
    r"\d{4}-\d{2}-\d{2}",
]

# Headlines ending with these look truncated (cut off mid-sentence)
TRUNCATION_WORDS: Final[set[str]] = {
    "a", "an", "the", "to", "for", "of", "in", "on", "at",
    "and", "or", "but", "as", "with", "from", "by", "into",
    "over", "through", "during", "before", "after", "above",
    "below", "between", "among", "within", "without", "under",
    "is", "are", "was", "were", "been", "be", "being",
    "has", "have", "had", "did", "do", "does", "so", "such",
    "this", "that", "these", "those", "which", "when", "where",
    "while", "who", "how", "what", "why", "will", "would",
    "could", "should", "may", "might", "must", "can", "about",
    "around", "up", "down", "out", "off", "across", "along",
    "according", "per", "via", "since", "due",
    "after", "despite", "following", "amid", "amidst",
    # Nouns that almost always signal truncation when they end a headline
    "financial", "policy", "growth", "markets", "market", "economy",
    "industry", "sector", "investment", "investment", "strategy",
    "regulation", "reform", "innovation", "growth", "decline",
    # Adjectives commonly left dangling
    "positive", "negative", "significant", "major", "potential",
}

# Phrases that flag non-news / generic content — filter these out
NON_NEWS_PATTERNS: Final[list[str]] = [
    r"(?i)\b(definition|definiton|defenition|what is|how it works?|guide to|explained|101|tutorial|overview)\b",
    r"(?i)\b(buy now|shop now|subscribe|click here)\b",
    r"(?i)\b(opens? in new tab)\b",
    # Product releases, market-size reports, etc. that aren't actual news
    r"(?i)\b(release date|release schedule|market size to hit|market size is expected|roundup|headlines)\b",
    r"(?i)\b(ios \d+|iphone \d+|android \d+|windows \d+|macos)\b",
]

# Minimum engagement threshold for Reddit posts
MIN_REDDIT_UPVOTES: Final[int] = 50


class TopicDiscoverer:
    """Fetch trending headlines and extract topic strings."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AfricanPulse/1.0"
        })

    # ── Public ──────────────────────────────────────────────

    def discover(self, *, count: int = 15, reddit_posts: int = 20) -> list[dict]:
        """Return a list of topic dicts with 'headline' + 'query' fields.

        Each dict: {
            'headline': str,   # Display-ready title from the source
            'query': str,      # Search-friendly query for news_client / research
        }
        """
        raw_headlines: list[dict] = []

        # 1. Google News RSS feeds
        for url in GOOGLE_NEWS_FEEDS:
            try:
                raw_headlines.extend(self._fetch_google_rss(url))
            except Exception:
                logger.warning(f"Google News RSS failed: {url}")

        # 2. Reddit hot posts
        for sub in REDDIT_SUBREDDITS:
            try:
                raw_headlines.extend(self._fetch_reddit_hot(sub, limit=reddit_posts))
            except Exception:
                logger.warning(f"Reddit hot fetch failed: r/{sub}")

        logger.info(f"Topic discovery: fetched {len(raw_headlines)} raw headlines")

        # 3. Extract topics (headline + query from each)
        topics = self._extract_topics(raw_headlines)

        # 4. Score, rank, and deduplicate
        ranked = self._rank_topics(topics)

        # Build output dicts with headline + query
        selected = [
            {
                "headline": t["headline"],
                "query": t["query"],
            }
            for t in ranked[:count]
        ]
        logger.info(f"Topic discovery: selected {len(selected)} unique topics")
        return selected

    # ── Source fetchers ─────────────────────────────────────

    def _fetch_google_rss(self, url: str) -> list[dict]:
        """Parse Google News RSS and return [{title, source, pubDate}]."""
        from xml.etree import ElementTree as ET

        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        items = []
        for item in root.findall(".//item"):
            title = item.findtext("title", "") or ""
            # Get source if available (newer GN RSS has <source> tag)
            source = item.findtext("source", "")
            # If no <source>, try stripping " - Some Name" at the end
            if not source:
                m = re.search(r"\s*-\s*([^-]{2,})$", title.strip())
                if m:
                    source = m.group(1).strip()
                    title = re.sub(r"\s*-\s*[^-]+$", "", title.strip())
            title = title.strip()
            if not title or len(title) < 15:
                continue
            items.append({
                "title": title,
                "source": source or "news",
                "pub_date": item.findtext("pubDate", ""),
                "origin": "google-news",
            })
        return items

    def _fetch_reddit_hot(self, subreddit: str, limit: int = 20) -> list[dict]:
        """Fetch hot posts from a subreddit.

        Two paths, because unauthenticated reddit.com/*.json now returns 403
        and app registration is gated behind manual approval:

        1. OAuth, when REDDIT_CLIENT_ID/SECRET are set — carries upvotes, so
           low-engagement posts can be filtered out.
        2. Atom RSS otherwise — still public, but carries no score field. The
           upvote filter is skipped rather than applied against a fake 0, which
           would discard every post.

        Returns [] on failure; discovery falls back to Google News alone.
        """
        import reddit_client

        if reddit_client.is_configured():
            data = reddit_client.get(f"/r/{subreddit}/hot", {"limit": limit})
            if not data:
                return []

            items = []
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                upvotes = post.get("ups", 0)
                # Skip low-engagement posts
                if upvotes < MIN_REDDIT_UPVOTES:
                    continue
                title = post.get("title", "")
                if not title or len(title) < 15:
                    continue
                items.append({
                    "title": self._clean_reddit_title(title, subreddit),
                    "source": f"r/{subreddit}",
                    "upvotes": upvotes,
                    "origin": "reddit",
                })
            return items

        # RSS path — headlines only, no engagement data.
        import config
        if not config.USE_REDDIT_RSS:
            return []

        items = []
        for entry in reddit_client.get_rss(f"/r/{subreddit}/hot/.rss")[:limit]:
            title = entry.get("title", "")
            if not title or len(title) < 15:
                continue
            items.append({
                "title": self._clean_reddit_title(title, subreddit),
                "source": f"r/{subreddit}",
                "upvotes": 0,          # unavailable via RSS
                "origin": "reddit-rss",
            })
        return items

    # ── Topic extraction & cleaning ────────────────────────

    @staticmethod
    def _clean_reddit_title(title: str, subreddit: str) -> str:
        """Strip subreddit-specific noise from titles."""
        # Remove flairs like [Discussion], [News], etc.
        title = re.sub(r"\[.*?\]\s*", "", title)
        title = re.sub(r"\s+", " ", title).strip()
        return title

    @classmethod
    def _clean_headline(cls, headline: str) -> str:
        """Strip publication names, dates, and other noise."""
        clean = headline.strip()
        for pattern in NOISE_PATTERNS:
            clean = re.sub(pattern, "", clean, flags=re.IGNORECASE)
        # Remove multiple spaces
        clean = re.sub(r"\s+", " ", clean).strip()
        # Remove trailing punctuation artifacts
        clean = clean.rstrip("-|\n")
        return clean

    @classmethod
    def _looks_truncated(cls, text: str) -> bool:
        """Detect headlines that end mid-sentence (cut off by RSS or bad stripping)."""
        stripped = text.strip()
        if not stripped:
            return True
        # Starts with colon — broken title (e.g., ": Trump dismisses...")
        if stripped.startswith(":") or stripped.startswith("-"):
            return True
        # Ends with preposition / article / conjunction → likely cut off
        last_word = stripped.split()[-1].lower().rstrip(".,;:?!")
        if last_word in TRUNCATION_WORDS:
            return True
        # Ends with a number fragment like "three-year" or "$50" — RSS truncated
        if re.search(r"[a-z]+-\d{4}$", stripped, re.I) or re.search(r"\d[\d,]*$", stripped):
            # Also check: is the last real word a truncation word?
            words = stripped.split()
            if len(words) >= 2 and words[-2].lower().rstrip(".,;:?!") in TRUNCATION_WORDS:
                return True
            # Ends with "three-year" or "50 billion" but no following noun → cut
            if re.search(r"(\d+[a-z]*|[a-z]+-\d+)$", stripped, re.I):
                # But allow complete things like "reaches three-year high" where "high" is the real end
                if len(words) >= 1:
                    last_real = words[-1].lower().rstrip(".,;:?!")
                    # Allow "high", "low", "level", "mark", "peak", "record", "all-time" as endings
                    if last_real in {"high", "low", "level", "mark", "peak", "record"}:
                        return False
        return False

    @classmethod
    def _extract_topics(cls, headlines: list[dict]) -> list[dict]:
        """Convert headlines into topic dicts with headline + query + relevance."""
        topics = []
        seen_titles = set()

        for item in headlines:
            title = cls._clean_headline(item.get("title", ""))
            if not title or len(title) < 20:
                continue

            # Filter out non-news / educational garbage
            if any(re.search(pat, title) for pat in NON_NEWS_PATTERNS):
                continue

            # Reject titles that look truncated (cut off mid-sentence)
            if cls._looks_truncated(title):
                logger.debug(f"Skipping truncated headline: {title[:80]}...")
                continue

            # Deduplicate by exact match
            key = title.lower()[:100]
            if key in seen_titles:
                continue
            seen_titles.add(key)

            # Check financial relevance
            relevance = cls._score_relevance(title)
            if relevance <= 0.3:  # skip purely off-topic headlines
                continue

            # headline  = display text (what the source published, cleaned)
            # query     = search-friendly string for news_client / Google News
            query = cls._headline_to_topic(title)

            topics.append({
                "headline": title,
                "query": query,
                "relevance": relevance,
                "source": item.get("source", "unknown"),
                "upvotes": item.get("upvotes", 0),
                "origin": item.get("origin", "unknown"),
            })

        return topics

    @classmethod
    def _score_relevance(cls, headline: str) -> float:
        """Score how 'finance/macro/crypto' a headline is (0-1)."""
        text = headline.lower()
        matches = sum(1 for kw in ALL_KEYWORDS if kw in text)
        if matches >= 3:
            return 1.0
        if matches == 2:
            return 0.8
        if matches == 1:
            return 0.6
        # If it has money-related numbers but no keyword match, give a small bump
        if re.search(r"\$[\d,.]+|\d+\s*(billion|million|bn|mn|%)|\d+\.?\d+%", text):
            return 0.4
        return 0.2

    @classmethod
    def _headline_to_topic(cls, headline: str) -> str:
        """Convert a headline into a concise topic string for research.

n        Examples:
            "Bitcoin hits all-time high as ETF inflows surge"
            -> "Bitcoin price action ETF inflows"

            "Fed holds rates steady but signals cautious stance"
            -> "Federal Reserve interest rates policy stance"
        """
        # Strip trailing punctuation
        text = re.sub(r"[?.!]+$", "", headline.strip())
        text = re.sub(r"\s+", " ", text)  # collapse whitespace

        # If the headline mentions a key financial entity + action,
        # create a focused topic string
        lowered = text.lower()

        # Bitcoin / Crypto
        if any(kw in lowered for kw in ("bitcoin", "btc")):
            return cls._compose_topic(text, "Bitcoin price action ETF flows")
        if any(kw in lowered for kw in ("ethereum", "eth")):
            return cls._compose_topic(text, "Ethereum staking Dencun upgrade")

        # Fed / Rates
        if "fed" in lowered or "federal reserve" in lowered:
            return cls._compose_topic(text, "US Federal Reserve interest rates dot plot")
        if "inflation" in lowered or "cpi" in lowered or "pce" in lowered:
            return cls._compose_topic(text, "US inflation CPI PCE data")
        if "unemployment" in lowered or "jobs" in lowered or "nfp" in lowered:
            return cls._compose_topic(text, "US unemployment jobs report NFP")
        if "treasury" in lowered or "yield" in lowered:
            return cls._compose_topic(text, "US Treasury yields 10-year bond")

        # ECB / Europe
        if "ecb" in lowered or "european central bank" in lowered:
            return cls._compose_topic(text, "ECB interest rates eurozone inflation")
        if "eurusd" in lowered or "euro" in lowered:
            return cls._compose_topic(text, "Euro EURUSD parity outlook")

        # China / Asia
        if "china" in lowered or "pboc" in lowered:
            return cls._compose_topic(text, "China economy PBOC stimulus")
        if "japan" in lowered or "boj" in lowered:
            return cls._compose_topic(text, "Japan BoJ rates yen intervention")

        # Oil / Commodities
        if "oil" in lowered or "opec" in lowered:
            return cls._compose_topic(text, "oil prices WTI Brent OPEC")
        if "gold" in lowered:
            return cls._compose_topic(text, "gold prices safe haven flows")

        # Trade / Geopolitics
        if "tariff" in lowered or "trade war" in lowered or "trade" in lowered:
            return cls._compose_topic(text, "trade war tariffs sanctions")

        # ── Default: strip rhetorical fluff and produce a clean query string ──
        # Remove time-based noise (e.g. "3 hours ago", "2024-05-01")
        cleaned = re.sub(r"\b\d+\s*(hours?|days?|months?|years?)\s*(ago|old)\b", "", text, flags=re.I)
        cleaned = re.sub(r"\b\d{4}\b", "", cleaned)
        # Strip leading rhetorical prefixes: "Up, or down?", "Will X...", "—" etc.
        cleaned = re.sub(r'^[—–-]\s*', '', cleaned)
        cleaned = re.sub(r'^[^a-zA-Z]*', '', cleaned)
        # Drop standalone fragments before the colon ("Up, or down? War..." -> "War...")
        if ':' in cleaned or '?' in cleaned:
            # Take the longer half — that's usually the actual headline
            parts = re.split(r'[\?:]', cleaned, maxsplit=1)
            if len(parts) == 2:
                left, right = parts[0].strip(), parts[1].strip()
                if len(right) > len(left):
                    cleaned = right
                else:
                    cleaned = left if left else right
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Trim trailing ellipsis/"..."  (search engines don’t need them)
        cleaned = re.sub(r'\.{3,}$', '', cleaned).strip()
        cleaned = re.sub(r'\.{1,2}$', '', cleaned).strip()
        return cleaned or headline

    # Cluster keywords: headlines sharing any of these groups are treated as redundant
    _CLUSTER_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
        "iran": ("iran", "tehran", "persian gulf", "strait of hormuz"),
        "oil": ("oil", "wti", "brent", "opec", "gasoline", "petrol"),
        "btc": ("bitcoin", "btc"),
        "eth": ("ethereum", "eth"),
        "fed": ("fed", "federal reserve"),
        "inflation": ("inflation", "cpi", "pce"),
        "ecb": ("ecb", "european central bank"),
        "oil_prices": ("oil", "opec", "crude", "brent"),
        "gold": ("gold", "precious metal"),
    }

    @classmethod
    def _topic_cluster_key(cls, topic: str) -> str | None:
        """Return cluster name if topic belongs to a known cluster."""
        t = topic.lower()
        for cluster_name, keywords in cls._CLUSTER_KEYWORDS.items():
            if any(kw in t for kw in keywords):
                return cluster_name
        return None

    @staticmethod
    def _compose_topic(headline: str, default: str) -> str:
        """If the headline gives enough detail, derive from it; else use default."""
        words = headline.split()
        if len(words) <= 3:
            return default

        # If headline has numbers or very specific named entities, derive from headline
        has_numbers = bool(re.search(r"\b\d[\d,.%]*\b", headline))
        specific_terms = ("hits", "surges", "plunges", "rally", "crash", "spike",
                          "surge", "drops", "rise", "fall", "record", "high",
                          "low", "worst", "best", "since", "amid", "after")
        has_specific = any(term in headline.lower() for term in specific_terms)

        if has_numbers or has_specific:
            # Derive topic from headline words, but clean them up
            cleaned = re.sub(r"[?.!]+$", "", headline.strip())
            # Remove text in quotes or parentheses
            cleaned = re.sub(r'["“”‘’].*?["“”‘’]', '', cleaned)
            cleaned = re.sub(r"\(.*?\)", "", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            # Truncate to roughly 6-10 words
            words_cleaned = cleaned.split()
            if len(words_cleaned) > 10:
                cleaned = " ".join(words_cleaned[:10])
            truncated = cleaned or headline
            # Normalize entities that map poorly
            entity_map = {
                "iran": "Iran conflict geopolitical risk",
                "fed": "US Federal Reserve interest rates",
                "ecb": "ECB interest rates eurozone",
                "bitcoin": "Bitcoin price action ETF",
                "gold": "gold prices safe haven",
                "oil": "oil prices WTI Brent OPEC",
            }
            low = truncated.lower()
            for entity, template in entity_map.items():
                if entity in low:
                    # Blend: template + unique headline detail
                    words_headline = low.split()
                    specific = ("surge" in low or "plunge" in low or "spike" in low or
                                "slump" in low or "rally" in low or "crash" in low)
                    if specific:
                        return f"{template} " + " ".join(
                            w for w in words_headline if w in ("surge", "plunge", "spike", "slump", "rally", "crash", "rises", "falls")
                        )
                    return template
            return truncated

        # Default: use the template (headline too generic)
        return default

    # ── Ranking & deduplication ────────────────────────────

    # Named entities / key terms for semantic overlap detection
    _ENTITY_PATTERNS: Final[list[tuple[str, re.Pattern]]] = [
        ("iran", re.compile(r"\biran\b", re.I)),
        ("israel", re.compile(r"\bisrael\b", re.I)),
        ("ukraine", re.compile(r"\bukraine\b", re.I)),
        ("russia", re.compile(r"\brussia\b", re.I)),
        ("china", re.compile(r"\bchina\b", re.I)),
        ("fed", re.compile(r"\bfed(er)?\b", re.I)),
        ("ecb", re.compile(r"\becb\b", re.I)),
        ("boj", re.compile(r"\bboj\b", re.I)),
        ("bitcoin", re.compile(r"\bbitcoin\b", re.I)),
        ("ethereum", re.compile(r"\beth(ereum)?\b", re.I)),
        ("oil", re.compile(r"\boil\b", re.I)),
        ("gold", re.compile(r"\bgold\b", re.I)),
    ]

    @classmethod
    def _shared_entities(cls, a: str, b: str) -> set[str]:
        """Return set of named entities shared between two strings."""
        entities = set()
        for name, pat in cls._ENTITY_PATTERNS:
            found_a = bool(pat.search(a))
            found_b = bool(pat.search(b))
            if found_a and found_b:
                entities.add(name)
        return entities

    @staticmethod
    def _stem_word(word: str) -> str:
        """Simple stemming — remove trailing s/ing/ed and lower."""
        w = word.lower().strip()
        for suffix in ("ing", "ed", "s"):
            if w.endswith(suffix) and len(w) > len(suffix) + 2:
                w = w[:-len(suffix)]
                break
        return w

    @classmethod
    def _word_overlap(cls, a: str, b: str) -> float:
        """Return word overlap ratio between two strings (0-1), with stemming."""
        words_a = {cls._stem_word(w) for w in re.sub(r"[^\w\s]", "", a).split()}
        words_b = {cls._stem_word(w) for w in re.sub(r"[^\w\s]", "", b).split()}
        # Remove tiny words that don't help dedup
        words_a = {w for w in words_a if len(w) > 2}
        words_b = {w for w in words_b if len(w) > 2}
        return len(words_a & words_b) / max(len(words_a), len(words_b), 1)

    @classmethod
    def _rank_topics(cls, topics: list[dict]) -> list[dict]:
        """Score, sort, and deduplicate topics. Returns full dicts intact."""
        # Tag each topic with its cluster and score
        scored = []
        for t in topics:
            upvote = t.get("upvotes", 0)
            upvote_factor = 1.0 + (0.2 if upvote > 500 else 0.0)
            score = t["relevance"] * upvote_factor
            cluster_key = cls._topic_cluster_key(t["headline"])
            scored.append({
                "score": score,
                "topic_dict": t,
                "headline": t["headline"],
                "cluster": cluster_key,
            })

        # Sort descending by score
        scored.sort(key=lambda x: x["score"], reverse=True)

        # Deduplicate by cluster + exact string + word overlap
        seen_exact = set()
        seen_clusters = set()
        kept_headlines = []  # for word-overlap dedup
        result = []
        for item in scored:
            topic_dict = item["topic_dict"]
            headline = item["headline"]

            # Exact dedup on headline (not query, as queries may collide)
            key_exact = headline.lower()[:80]
            if key_exact in seen_exact:
                continue
            seen_exact.add(key_exact)

            # Cluster dedup (e.g., "iran")
            cluster = item["cluster"]
            if cluster and cluster in seen_clusters:
                continue
            if cluster:
                seen_clusters.add(cluster)

            # Word-overlap + entity dedup against previously kept headlines
            is_near_dup = False
            for kept in kept_headlines:
                word_overlap = cls._word_overlap(headline, kept)
                shared_entities = cls._shared_entities(headline, kept)
                # Same story if: significant word overlap OR same key entity + some overlap
                if word_overlap > 0.20:
                    is_near_dup = True
                    break
                if shared_entities and word_overlap > 0.10:
                    is_near_dup = True
                    break
            if is_near_dup:
                continue

            kept_headlines.append(headline)
            result.append(topic_dict)

        return result


# ── Public API ────────────────────────────────────────────

def discover_topics(*, count: int = 15) -> list[dict]:
    """Return trending topic objects with 'headline' and 'query' keys."""
    discoverer = TopicDiscoverer()
    return discoverer.discover(count=count)


# ── Quick diagnostic ──────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Ensure UTF-8 output on Windows
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("Discovering trending topics...\n")
    topics = discover_topics(count=15)
    for i, t in enumerate(topics, 1):
        print(f"  {i}. [H] {t['headline']}")
        print(f"      [Q] {t['query']}\n")

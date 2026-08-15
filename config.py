"""Configuration — API keys, paths, topics, thresholds."""

import os
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ─── API Keys ──────────────────────────────────────────────
# NVIDIA NIM (build.nvidia.com) — primary LLM provider
NVIDIA_NIM_API_KEY = os.environ.get("NVIDIA_NIM_API_KEY", "")
NIM_BASE_URL = os.environ.get("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Optional: Perplexity API key for AI-enhanced research synthesis
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")

# Reddit OAuth — app-only read access. Unauthenticated .json endpoints now
# return 403, so without these every Reddit source is silently skipped.
# Register a "script" app at https://www.reddit.com/prefs/apps
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get(
    "REDDIT_USER_AGENT", "windows:worldpulse:1.0 (by /u/worldpulse)"
)

# Reddit's Atom feeds are the only free path left without approved API access,
# but they rate-limit to ~10 req/min, so reading the subreddit list costs about
# 6 minutes and still loses a few feeds to 429. Worth it for the retail-sentiment
# topics Google News does not surface; set false to skip Reddit entirely.
# Ignored when OAuth credentials are set — those are faster and unthrottled.
USE_REDDIT_RSS = os.environ.get("USE_REDDIT_RSS", "true").lower() in ("1", "true", "yes")

# Telegram delivery
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── Daily topic list ──────────────────────────────────────
# Covers global digital assets, macroeconomics, and geopolitics
DAILY_TOPICS = [
    # --- DIGITAL ASSETS & CRYPTO ---
    "Bitcoin price action ETF flows",
    "Ethereum staking Dencun upgrade",
    "DeFi TVL trends Uniswap Aave",
    "stablecoins USDT USDC regulation",
    "crypto exchange Binance Coinbase",
    "altcoin market cap dominance",
    "Bitcoin halving supply impact",

    # --- US MACRO & MONETARY POLICY ---
    "US Federal Reserve interest rates dot plot",
    "US inflation CPI PCE data",
    "US Treasury yields 10-year bond",
    "US dollar DXY strength",
    "US unemployment jobs report NFP",
    "US fiscal deficit debt ceiling",

    # --- EUROPE & UK ---
    "ECB interest rates eurozone inflation",
    "UK Bank of England rates GBP",
    "Euro EURUSD parity outlook",
    "European energy gas prices",

    # --- ASIA & PACIFIC ---
    "China economy PBOC stimulus",
    "Japan BoJ rates yen intervention",
    "India rupee inflation RBI",
    "Australia RBA rates AUD",
    "South Korea won semiconductor exports",

    # --- EMERGING MARKETS ---
    "Brazil central bank rates BRL",
    "Mexico Banxico rates peso",
    "Turkey lira inflation central bank",
    "South Africa SARB rand rates",
    "Nigeria naira CBN policy FX",

    # --- COMMODITIES & ENERGY ---
    "oil prices WTI Brent OPEC",
    "gold prices safe haven flows",
    "copper industrial demand China",
    "lithium EV battery supply",
    "grain wheat corn Ukraine exports",

    # --- GEOPOLITICS & TRADE ---
    "trade war tariffs sanctions",
    "Middle East conflict oil risk",
    "Taiwan semiconductor geopolitics",
    "Russia sanctions commodities",
    "BRICS currency de-dollarisation",

    # --- TRADITIONAL FINANCE ---
    "banking crisis credit risk",
    "fintech disruption payments",
    "cross border remittances corridor",
    "sovereign debt default risk",
    "private credit bubble risk",
]

# ─── Paths ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
L30_CACHE_DIR = os.path.join(BASE_DIR, "cache", "last30days")
DEEP_DIVE_CACHE_DIR = os.path.join(BASE_DIR, "cache", "deep_dive")
INDEX_DIR = os.path.join(BASE_DIR, "vector_index")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# ─── Thresholds ───────────────────────────────────────────
DUPLICATE_THRESHOLD = 0.92   # turbovec similarity score above which a topic is skipped
MIN_TOPIC_SCORE = 0.3        # minimum combined score to include a topic
MAX_DAILY_PICKS = 2          # max articles+scripts to generate per day
# Engagement score above which Agent-Reach fires. Calibrated 2026-08-15 against
# 12 sampled topics under the velocity-based score in news_client. Observed
# range 0 (Nigeria naira CBN, nothing published in a week) to 4398 (Middle East
# conflict oil risk, 48 articles in 24h); median 266. 800 fires on roughly the
# top third -- genuinely breaking stories rather than a fixed quota.
# The previous value of 500 was unreachable: the old formula's ceiling without
# Reddit was 400, so deep dives never ran at all.
DEEP_DIVE_THRESHOLD = 800

# ─── Feature toggles ──────────────────────────────────────
# Humanizer pass: if True, both original + humanized are saved.
# If False, only original is produced (humanize step skipped).
HUMANIZE_DEFAULT = os.environ.get("HUMANIZE", "false").lower() in ("1", "true", "yes")

# Dynamic topic discovery: if True, fetches trending headlines from
# Google News + Reddit instead of using the static DAILY_TOPICS list.
# Set via env var or toggle here directly.
USE_DYNAMIC_TOPICS = os.environ.get("USE_DYNAMIC_TOPICS", "true").lower() in ("1", "true", "yes")

# Publishing toggles — set true to enable auto-posting
POST_SUBSTACK = os.environ.get("POST_SUBSTACK", "false").lower() in ("1", "true", "yes")
POST_X = os.environ.get("POST_X", "false").lower() in ("1", "true", "yes")

# ─── Retry settings ──────────────────────────────────────
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds

# ─── LLM Settings ────────────────────────────────────────
# Model selection lives in nim_client.MODEL_POOL, routed per task.
ARTICLE_MAX_TOKENS = 1500
SCRIPT_MAX_TOKENS = 600

# WorldPulse

Global macro, micro & crypto news intelligence pipeline. Discovers trending topics, researches them across multiple sources, scores and picks the best, then generates a Substack article + short video script via LLM and delivers to Telegram.

---

## What it does

1. **Discovers** — Fetches live trending topics from Google News + Reddit via `topic_discoverer.py`
2. **Researches** — Gathers data from Google News RSS, regional feeds, and optional Perplexity API via `news_client.py`
3. **Scores** — Ranks topics by engagement and deduplicates via vector similarity via `topic_scorer.py`
4. **Deep-dives** — For top topics, pulls raw community data (Twitter, YouTube, Web) via `agent_reach.py`
5. **Generates** — Article + script via NVIDIA NIM LLMs via `generator_article.py` / `generator_script.py`
6. **Delivers** — Sends briefing, article, and script to Telegram via `telegram_bot.py`
7. **Optionally publishes** — Substack (SMTP) and X (Twitter) via `posts.py`

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt        # runtime
pip install -r requirements-dev.txt    # + pytest, for running tests

# 2. Set up environment
cp .env.example .env
# Edit .env with your keys (see Environment below)

# 3. Run the pipeline manually
python run_once.py

# 4. Or run with a fresh start (clears vector index)
python run_fresh.py

# 5. Or start the daily scheduler (runs at 07:00 WAT)
python main.py
```

---

## Environment

Copy `.env.example` to `.env` and fill in your keys:

```
# Telegram (required for delivery)
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# NVIDIA NIM (required for content generation)
NVIDIA_NIM_API_KEY=nvapi-...
NIM_BASE_URL=https://integrate.api.nvidia.com/v1

# Perplexity (optional — for enhanced research synthesis)
PERPLEXITY_API_KEY=pplx-...

# Substack (optional — for newsletter posting)
SUBSTACK_SMTP_SERVER=smtp.gmail.com
SUBSTACK_SMTP_PORT=587
SUBSTACK_SMTP_USER=your-email@gmail.com
SUBSTACK_SMTP_PASSWORD=your-app-password
SUBSTACK_POST_EMAIL=post-12345@substack.com

# X / Twitter (optional — for social posting)
X_API_KEY=your-consumer-key
X_API_SECRET=your-consumer-secret
X_ACCESS_TOKEN=your-access-token
X_ACCESS_SECRET=your-access-secret
```

### Getting an NVIDIA NIM API key

1. Go to https://build.nvidia.com
2. Sign in and generate an API key
3. Paste it into `.env` as `NVIDIA_NIM_API_KEY`

---

## Architecture

```
main.py → scheduler.py → research.py → news_client.py
                                    → topic_discoverer.py
                          topic_scorer.py
                          agent_reach.py (deep dive)
                          generator_article.py → nim_client.py
                          generator_script.py → nim_client.py
                          telegram_bot.py (delivery)
                          posts.py (optional publish)
```

---

## File Map

| File | Purpose |
|------|---------|
| `main.py` | Entry point — starts APScheduler |
| `run_once.py` | Manual single pipeline run |
| `run_fresh.py` | Clear vector index + run pipeline |
| `scheduler.py` | Full pipeline orchestrator |
| `research.py` | Two-stage research orchestrator |
| `news_client.py` | Google News + Reddit + RSS research client |
| `topic_discoverer.py` | Live topic discovery from Google News + Reddit |
| `topic_scorer.py` | Topic deduplication and scoring |
| `generator_article.py` | Substack article generation via LLM |
| `generator_script.py` | Short video script generation via LLM |
| `humanizer.py` | Optional humanization pass for content |
| `nim_client.py` | NVIDIA NIM LLM client with model fallback |
| `agent_reach.py` | Multi-tier data source (Twitter, Reddit, YouTube, Web) |
| `telegram_bot.py` | Telegram delivery |
| `posts.py` | Substack + X/Twitter posting |
| `vector_store.py` | Vector similarity and content indexing |
| `config.py` | Global configuration, topics, thresholds |
| `logger.py` | Structured logging |

---

## Config Toggles

In `config.py`, you can adjust:

| Setting | Default | What it does |
|---------|---------|-------------|
| `USE_DYNAMIC_TOPICS` | `True` | Use live topic discovery instead of static `DAILY_TOPICS` list |
| `HUMANIZE_DEFAULT` | `False` | Apply humanization pass to generated content |
| `MAX_DAILY_PICKS` | `2` | Max articles+scripts to generate per run |
| `DEEP_DIVE_THRESHOLD` | `500` | Engagement score above which Agent-Reach fires |
| `DUPLICATE_THRESHOLD` | `0.92` | Similarity score above which topics are skipped |
| `POST_SUBSTACK` | `False` | Auto-publish to Substack |
| `POST_X` | `False` | Auto-post to X/Twitter |

---

## Directory Structure

```
WorldPulse/
├── main.py                  # Scheduler entry point
├── run_once.py              # One-shot pipeline
├── run_fresh.py             # Fresh start (clears index)
├── config.py                # Configuration & topics
├── scheduler.py             # Pipeline logic
├── research.py              # Research orchestrator
├── news_client.py           # News/RSS research
├── topic_discoverer.py      # Live topic discovery
├── topic_scorer.py          # Topic scoring
├── generator_article.py     # Article generation
├── generator_script.py      # Script generation
├── humanizer.py             # Humanization pass
├── nim_client.py            # LLM client
├── agent_reach.py           # Source layer (Twitter, YouTube, Web)
├── telegram_bot.py          # Telegram delivery
├── posts.py                 # Social publishing
├── vector_store.py          # Vector indexing
├── logger.py                # Logging
├── tests/                   # pytest suite (pure logic, vector_store mocked)
├── .github/
│   └── workflows/
│       └── ci.yml           # GitHub Actions CI (compile check + pytest)
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # Lean test dependencies (no PyTorch)
├── pytest.ini
├── LICENSE
├── .env.example             # Env template
├── .gitignore               # Git ignore rules
├── archive/                 # Archived dev/test files (gitignored, local only)
│   ├── test_agent_reach.py
│   ├── test_nim.py
│   ├── test_pipeline.py
│   ├── verify_pipeline.py
│   └── SESSION_SUMMARY.md
├── cache/                   # Cache (auto-created)
│   ├── last30days/          # Research cache
│   ├── deep_dive/           # Agent-Reach cache
│   └── nim_llm/             # LLM response cache
├── outputs/                 # Generated content (auto-created)
│   ├── articles/            # Substack articles
│   └── scripts/             # Video scripts
├── vector_index/            # Vector index (auto-created)
└── logs/                    # Logs (auto-created)
```

---

## Agent-Reach Sources

Every source uses a 3-tier fallback hierarchy — if one method fails, it silently tries the next:

| Source | Tier 1 | Tier 2 | Tier 3 |
|--------|--------|--------|--------|
| **Twitter/X** | `twitter` CLI | Nitter JSON proxy | Nitter HTML scrape |
| **Reddit** | `rdt` CLI | Reddit JSON API | — |
| **YouTube** | `yt-dlp` | `youtube-transcript-api` | Caption scrape |
| **Web** | Jina Reader | Raw fetch + HTML strip | — |

Only `yt-dlp` needs installation on most systems (`winget install yt-dlp`). The rest are optional.

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

Covers `topic_discoverer.py` (regex/scoring logic), `topic_scorer.py` (with `vector_store` mocked), `humanizer.py`, and `telegram_bot.py`'s message-splitting — no network calls, no API keys, no heavy ML dependencies required. `requirements-dev.txt` deliberately skips `sentence-transformers` (it's lazy-loaded only when embeddings actually run, which the test suite avoids by mocking around `vector_store`), so CI stays fast. CI runs this suite plus a compile check on every push and PR.

---

## License

MIT — see [LICENSE](LICENSE).

"""Generate Substack article drafts using the LLM."""

import os
from datetime import date

import config
from nim_client import generate_text
from vector_store import get_africa_context, remember_topic
from logger import logger

ARTICLE_OUTPUT_DIR = os.path.join(config.OUTPUT_DIR, "articles")

ARTICLE_SYSTEM_PROMPT = """\
You are the writer behind "WorldPulse" — a sharp, global finance and macro
newsletter. Your readers are professionals, traders, and serious investors
across all continents — from New York to London, from Singapore to São Paulo.
They follow global markets, central bank moves, crypto, commodities, and
geopolitics. They are not beginners. They want actionable insight, not filler.

Coverage philosophy:
- Cover global stories on their own merits. A Fed rate decision, an ECB pivot,
  a China stimulus package, a Nigeria FX policy shift — each gets covered as
  the significant global event it is.
- Do NOT force regional angles. A story about US Treasury yields does not need
  an "and in Africa..." paragraph. A story about Naira devaluation naturally
  belongs if Nigeria is at the centre of it.
- Your job is to spot signals, connect dots across regions, and tell readers
  what actually matters — not to tick geographic boxes.
- When a story has genuine multi-continental relevance (e.g. dollar strength
  hitting emerging markets, or oil shocks rippling through Europe and Asia),
  bring those connections in. Otherwise, keep it focused.

Your writing style:
- Conversational but sharp. Not academic, not tabloid.
- Grounded in real data, real community signals, and market moves — not
  press release rewrites.
- Short paragraphs. Varied sentence length. No bullet points in the body.
- Never uses AI filler phrases: "delve into", "navigate", "landscape",
  "it's worth noting", "vibrant tapestry", "it is important to", or any variation.
- Does not open with a rhetorical question.
- Does not end with a generic "what do you think?" closer.
- Has an opinion. Takes a stance. Does not just report both sides neutrally.

Article format:
- Headline: punchy and specific. Global angle, not forced regional framing.
- Opening paragraph: hook that states the situation directly, no warm-up
- Body: 400–600 words, 3–5 sections, no headers needed
- Closing: one strong paragraph with a clear takeaway
- Substack CTA at the very end: one line, no more
"""


def _retry_llm_call(func, *args, **kwargs):
    """Wrapper with exponential-backoff retry."""
    import time
    for attempt in range(config.MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == config.MAX_RETRIES - 1:
                raise
            wait = config.RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(f"LLM call failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
            time.sleep(wait)
    return None


def build_article_prompt(research: dict) -> str:
    topic = research.get("_topic", "")
    synthesis = research.get("synthesis", "")
    reddit_signals = research.get("reddit", [])
    x_signals = research.get("x", [])
    polymarket = research.get("polymarket", [])
    africa_context = get_africa_context(synthesis or topic, k=4)

    reddit_text = "\n".join(
        f"- r/{r.get('subreddit','')}: \"{r.get('title','')}\" ({r.get('upvotes',0)} upvotes)"
        for r in reddit_signals[:5]
    )
    x_text = "\n".join(f"- @{x.get('author','')}: {x.get('text','')}" for x in x_signals[:5])
    poly_text = "\n".join(
        f"- {p.get('question','')} — {p.get('probability','')}% odds"
        for p in polymarket[:3]
    )

    deep_dive = research.get("_deep_dive", {})
    raw_tweets = deep_dive.get("tweets", [])
    raw_reddit = deep_dive.get("reddit_posts", [])
    raw_transcript = deep_dive.get("youtube_transcript", "")

    deep_dive_section = ""
    if research.get("_deep_dive_fired"):
        tweet_text = "\n".join(f"- {t}" for t in raw_tweets[:6] if t)
        reddit_raw_text = "\n".join(
            f"- {p.get('title','')}: {p.get('body','')[:200]}"
            for p in raw_reddit[:3] if p
        )
        transcript_snippet = raw_transcript[:600] if raw_transcript else ""
        deep_dive_section = f"""
RAW COMMUNITY VOICES (direct from Twitter/Reddit via Agent-Reach — use specific quotes):
TWITTER RAW:
{tweet_text}

REDDIT THREAD TEXT:
{reddit_raw_text}

YOUTUBE TRANSCRIPT EXCERPT:
{transcript_snippet}
"""

    # Africa context: only include if the topic has any African relevance keywords
    africa_section = ""
    topic_lower = (topic or "").lower()
    if any(kw in topic_lower for kw in ("africa", "nigeria", "naira", "cbn", "kenya", "ghana",
                                          "south africa", "egypt", "morocco", "ethiopia", "afrexim")):
        africa_text = "\n".join(f"- {ctx}" for ctx in africa_context)
        if africa_text:
            africa_section = f"""
AFRICAN CONTEXT (only if it genuinely adds to the story):
{africa_text}
"""

    return f"""\
Today's topic: {topic}

RESEARCH SYNTHESIS (what the community is saying):
{synthesis}

TOP REDDIT SIGNALS:
{reddit_text}

TOP X / TWITTER SIGNALS:
{x_text}

PREDICTION MARKET SIGNALS (Polymarket):
{poly_text}
{deep_dive_section}{africa_section}
Today's date: {date.today().strftime('%B %d, %Y')}

Write a Substack article for "WorldPulse" using the above research.
This is a global finance and macro publication — stories get covered as global
stories. If there is a genuine regional dimension (African or otherwise) that
adds real insight, weave it in. If not, leave it out entirely.
If RAW COMMUNITY VOICES are present above, use specific quotes or reactions from them
to ground the article — attributed as "one trader on X" or "a thread on r/CryptoCurrency"
rather than made-up quotes. This is what makes the piece feel real.
Ground every claim in the specific signals above — do not invent data.
Output the article only. No preamble, no meta-commentary.
"""


def generate_article(research: dict) -> str:
    try:
        prompt = build_article_prompt(research)

        # Include system prompt in user message (long system prompts trigger
        # excessive thinking that consumes all tokens via the NIM proxy).
        full_prompt = f"{ARTICLE_SYSTEM_PROMPT}\n\n---\n\n{prompt}"

        article_text = generate_text(full_prompt, task="article")

        # Save locally
        os.makedirs(ARTICLE_OUTPUT_DIR, exist_ok=True)
        topic_slug = research.get("_topic", "article").lower().replace(" ", "_")
        filename = f"{date.today().isoformat()}_{topic_slug}.md"
        filepath = os.path.join(ARTICLE_OUTPUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(article_text)

        # Record the topic, not the article: the next run's dedup check queries
        # by topic, and storing the article instead is what made the check a
        # no-op for months.
        remember_topic(research.get("_topic", ""))
        return article_text
    except Exception:
        logger.error("Article generation failed", exc_info=True)
        return ""

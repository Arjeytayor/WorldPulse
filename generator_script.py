"""Generate YouTube Shorts script drafts using the LLM."""

import os
from datetime import date

import config
from nim_client import generate_text
from vector_store import get_africa_context
from logger import logger

SCRIPT_OUTPUT_DIR = os.path.join(config.OUTPUT_DIR, "scripts")

SCRIPT_SYSTEM_PROMPT = """\
You write YouTube Shorts scripts for "WorldPulse" — a global finance and macro
channel followed by serious investors, traders, and professionals across all
continents. They are not beginners. They want sharp, fast takes on what actually
matters in markets.

Coverage philosophy: cover global stories as global stories. A Fed pivot, a China
stimulus, an OPEC decision, a Naira devaluation — each gets treated as the
significant event it is. Do NOT force regional angles. Only bring in regional
context when it genuinely changes the meaning of the story.

The format is a 45–60 second vertical video. One person to camera, no B-roll needed.

Script rules:
- Start with a hook in the first 3 seconds that states the core fact or tension. No warm-up.
- Write as if talking to a smart friend who follows markets, not presenting to a boardroom.
- Maximum 150 words total. Every word earns its place.
- Structure: Hook → What happened → Why it matters → One clear takeaway
- If there is a genuine regional or multi-continental angle, include it in the
  "why it matters" beat. If there is not, skip it — the global takeaway is enough.
- End with a soft CTA: "Follow for daily finance takes" — nothing harder than that.
- Do NOT use: "In this video...", "Today we're going to...", "Make sure to like and subscribe"
- Do NOT use filler phrases or AI vocabulary.
- Include one specific number or data point from the research — makes it feel real.
- Mark where a text overlay would go: [OVERLAY: text here]
- Mark speaker pauses: [PAUSE]

Output format:
TITLE: (YouTube Shorts title, under 60 chars)
HOOK: (first 3 seconds — one punchy line)
SCRIPT:
(full script with overlay and pause markers)
CTA: (last line)
"""


def _retry_llm_call(func, *args, **kwargs):
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


def build_script_prompt(research: dict) -> str:
    topic = research.get("_topic", "")
    synthesis = research.get("synthesis", "")

    # Africa context: only include if the topic has African relevance keywords
    africa_section = ""
    topic_lower = (topic or "").lower()
    if any(kw in topic_lower for kw in ("africa", "nigeria", "naira", "cbn", "kenya", "ghana",
                                          "south africa", "egypt", "morocco", "ethiopia", "afrexim")):
        africa_context = get_africa_context(synthesis or topic, k=2)
        africa_text = "\n".join(f"- {ctx}" for ctx in africa_context)
        if africa_text:
            africa_section = f"""
Regional context (only if relevant to the story):
{africa_text}
"""

    deep_dive = research.get("_deep_dive", {})
    raw_tweets = deep_dive.get("tweets", [])
    best_quote = raw_tweets[0] if raw_tweets else ""
    quote_section = f'\nBest raw community quote to consider using:\n"{best_quote}"\n' if best_quote else ""

    return f"""\
Topic: {topic}

Research summary: {synthesis[:600]}
{quote_section}{africa_section}
Write a YouTube Shorts script using the above.
Ground it in at least one specific data point from the research.
If a raw community quote is provided above and it's punchy or specific,
you can paraphrase it in the script — attributed as "people on X are saying..."
or "one trader put it bluntly:". Never reproduce it verbatim as a quote unless
it's genuinely striking.
Output only the script in the format specified. No meta-commentary.
"""


def generate_script(research: dict) -> str:
    try:
        prompt = build_script_prompt(research)

        # Include system prompt in user message (long system prompts trigger
        # excessive thinking that consumes all tokens via the NIM proxy).
        full_prompt = f"{SCRIPT_SYSTEM_PROMPT}\n\n---\n\n{prompt}"

        script_text = generate_text(full_prompt, task="script")

        os.makedirs(SCRIPT_OUTPUT_DIR, exist_ok=True)
        topic_slug = research.get("_topic", "script").lower().replace(" ", "_")
        filename = f"{date.today().isoformat()}_{topic_slug}_script.md"
        filepath = os.path.join(SCRIPT_OUTPUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(script_text)

        return script_text
    except Exception:
        logger.error("Script generation failed", exc_info=True)
        return ""

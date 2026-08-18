"""Vector store — embed, deduplicate, retrieve.

Uses sentence-transformers for local embedding. The Africa context index is a
turbovec IdMapIndex so search results map back to human-readable strings;
topic deduplication uses a dated JSON sidecar instead (see below).
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
from turbovec import IdMapIndex

from logger import logger
from config import INDEX_DIR

RECENT_TOPICS_PATH = os.path.join(INDEX_DIR, "recent_topics.json")
AFRICA_INDEX_PATH = os.path.join(INDEX_DIR, "africa_context")
AFRICA_TEXTS_PATH = os.path.join(INDEX_DIR, "africa_context_texts.json")

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
DIM = 384

# Measured on this pipeline's own output (Aug 2026): the same subject on
# consecutive days scores 0.84-0.87, genuinely different subjects score
# 0.11-0.32. 0.70 sits in the empty gap between those two clusters. The
# previous 0.92 was above *both* of them, which is why the gate never fired.
#
# Known limit: a *heavily* reworded topic for the same subject ("gold rallies
# as investors seek safety" vs "gold prices safe haven flows") scores only
# 0.45-0.56 and slips through. Catching that would need a threshold near 0.40,
# which is barely above the 0.32 scored by two genuinely different finance
# subjects (bitcoin vs gold) -- and every topic here is a finance topic, so
# "fed rate decision" vs "ecb rate decision" would land in the same band. A
# missed duplicate costs one repeated brief; a false positive can drop a real
# story and empty the run. Held at 0.70 until there is a second signal
# (entity overlap) to disambiguate with.
DEDUP_THRESHOLD = 0.70

# After this many days a subject is fair game again. Gold genuinely does make
# news twice in a month; it just should not make it two mornings running.
DEDUP_WINDOW_DAYS = 7


@lru_cache(maxsize=1)
def _get_embedder():
    """Lazy-load the embedding model (singleton)."""
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(EMBED_MODEL_NAME)
    except ImportError:
        raise RuntimeError(
            "sentence-transformers is required.  Install it with:\n"
            "  pip install sentence-transformers"
        )


def embed(texts: list[str]) -> np.ndarray:
    """Return a float32 (N, 384) array of embeddings."""
    model = _get_embedder()
    return model.encode(texts, convert_to_numpy=True).astype(np.float32)


# ── Helpers ──────────────────────────────────────────────

def _load_or_create_index(path: str) -> IdMapIndex | None:
    """Load an existing IdMapIndex or return None."""
    if os.path.exists(path):
        try:
            return IdMapIndex.load(path)
        except Exception:
            logger.warning(f"Failed to load index from {path}, treating as empty")
    return None


def _save_index(index: IdMapIndex, path: str) -> None:
    """Persist an IdMapIndex to disk."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    index.write(path)


# ─── Recent-topic dedup ───────────────────────────────────
#
# This used to be a turbovec index of generated *articles*, queried with a
# research *synthesis*. Those are different kinds of text -- an article scores
# only 0.64 against a synthesis of its own subject -- so the check could never
# clear any threshold and no topic was ever actually filtered out. The unit
# that stays stable across days is the topic string, so that is what gets
# stored and what gets queried, and the two now match in kind.
#
# A dated JSON sidecar replaces the index: the window holds ~14 topics, and a
# plain dot product over 14 vectors is cheaper than maintaining a vector index
# that supports deletion. The old index also grew without bound and carried no
# dates, so it could not express "recent" at all.


def _load_recent(window_days: int) -> list[str]:
    """Topics covered inside the window."""
    if not os.path.exists(RECENT_TOPICS_PATH):
        return []
    try:
        with open(RECENT_TOPICS_PATH, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        logger.warning("recent_topics.json unreadable — treating as empty")
        return []

    cutoff = date.today() - timedelta(days=window_days)
    topics = []
    for entry in entries:
        try:
            if date.fromisoformat(entry["date"]) > cutoff:
                topics.append(entry["topic"])
        except (KeyError, TypeError, ValueError):
            continue  # one malformed row must not sink the whole check
    return topics


def remember_topic(topic: str) -> None:
    """Record that ``topic`` was covered today, dropping expired entries."""
    topic = (topic or "").strip()
    if not topic:
        return
    try:
        entries = []
        if os.path.exists(RECENT_TOPICS_PATH):
            try:
                with open(RECENT_TOPICS_PATH, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            except (OSError, ValueError):
                entries = []

        entries.append({"topic": topic, "date": date.today().isoformat()})

        # Prune on write, not only on read, so the file cannot grow without
        # bound the way the old content index did.
        cutoff = date.today() - timedelta(days=DEDUP_WINDOW_DAYS)
        kept = []
        for entry in entries:
            try:
                if date.fromisoformat(entry["date"]) > cutoff:
                    kept.append(entry)
            except (KeyError, TypeError, ValueError):
                continue

        os.makedirs(INDEX_DIR, exist_ok=True)
        with open(RECENT_TOPICS_PATH, "w", encoding="utf-8") as f:
            json.dump(kept, f, indent=2)
    except Exception:
        logger.error("Failed to record recent topic", exc_info=True)


def is_duplicate(
    text: str,
    threshold: float = DEDUP_THRESHOLD,
    window_days: int = DEDUP_WINDOW_DAYS,
) -> bool:
    """True if ``text`` names a subject already covered inside the window.

    ``text`` must be a *topic* string. Passing an article or a synthesis here
    compares unlike things and silently never matches -- that was the bug.
    """
    text = (text or "").strip()
    if not text:
        return False
    try:
        recent = _load_recent(window_days)
        if not recent:
            return False

        # all-MiniLM-L6-v2 L2-normalises its output, so a dot product already
        # is cosine similarity -- no separate normalisation step needed.
        vectors = embed([text] + recent)
        best = float((vectors[1:] @ vectors[0]).max())

        if best >= threshold:
            logger.info(
                f"Skipping '{text}' — {best:.3f} similar to a topic already "
                f"covered in the last {window_days} days"
            )
            return True
        return False
    except Exception:
        # Fail open: a broken dedup check should cost a repeated topic, never
        # an empty run.
        logger.error("Duplicate check failed", exc_info=True)
        return False


# ─── Africa context index ─────────────────────────────────

def get_africa_context(topic_text: str, k: int = 3) -> list[str]:
    """Return the top-k most relevant African/Nigerian context strings."""
    try:
        index = _load_or_create_index(AFRICA_INDEX_PATH)
        if index is None:
            return []

        if not os.path.exists(AFRICA_TEXTS_PATH):
            return []

        with open(AFRICA_TEXTS_PATH, "r", encoding="utf-8") as f:
            stored_texts = json.load(f)

        vector = embed([topic_text])  # (1, 384)
        scores, indices = index.search(vector, k=k)
        if indices is None or len(indices) == 0:
            return []

        results = []
        for idx in indices[0]:  # first (and only) query
            if 0 <= idx < len(stored_texts):
                results.append(stored_texts[idx])
        return results
    except Exception:
        logger.error("Africa context retrieval failed", exc_info=True)
        return []


def seed_africa_context(context_strings: list[str]) -> None:
    """One-time seed of the African/Nigerian finance context index."""
    try:
        os.makedirs(INDEX_DIR, exist_ok=True)
        vectors = embed(context_strings)
        index = IdMapIndex()
        ids = np.arange(len(context_strings), dtype=np.uint64)
        index.add_with_ids(vectors, ids)
        _save_index(index, AFRICA_INDEX_PATH)

        with open(AFRICA_TEXTS_PATH, "w", encoding="utf-8") as f:
            json.dump(context_strings, f, indent=2)
        print(f"Seeded {len(context_strings)} Africa context vectors.")
    except Exception:
        logger.error("Africa context seeding failed", exc_info=True)


def clear_recent_topics() -> None:
    """Forget every recently-covered topic (used by run_fresh.py)."""
    try:
        if os.path.exists(RECENT_TOPICS_PATH):
            os.remove(RECENT_TOPICS_PATH)
    except Exception:
        logger.error("Failed to clear recent topics", exc_info=True)

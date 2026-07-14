"""Vector store — embed, store, deduplicate, retrieve.

Uses sentence-transformers for local embedding and turbovec for fast,
quantised similarity search.  Both indexes are IdMapIndex so we can map
search results back to human-readable strings.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

import numpy as np
from turbovec import IdMapIndex

from logger import logger
from config import INDEX_DIR

CONTENT_INDEX_PATH = os.path.join(INDEX_DIR, "content")
AFRICA_INDEX_PATH = os.path.join(INDEX_DIR, "africa_context")
AFRICA_TEXTS_PATH = os.path.join(INDEX_DIR, "africa_context_texts.json")

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
DIM = 384


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


# ─── Content index (deduplication) ─────────────────────────

def add_content(texts: list[str]) -> None:
    """Add new ingested content to the main dedup index."""
    if not texts:
        return
    try:
        index = _load_or_create_index(CONTENT_INDEX_PATH)
        vectors = embed(texts)

        if index is None:
            index = IdMapIndex()
            ids = np.arange(len(texts), dtype=np.uint64)
            index.add_with_ids(vectors, ids)
        else:
            # Determine next ID to avoid collisions
            existing_count = len(index)
            start_id = existing_count
            ids = np.arange(start_id, start_id + len(texts), dtype=np.uint64)
            index.add_with_ids(vectors, ids)

        _save_index(index, CONTENT_INDEX_PATH)
    except Exception:
        logger.error("Failed to add content to vector store", exc_info=True)


def is_duplicate(text: str, threshold: float = 0.92) -> bool:
    """True if ``text`` is too similar to something already in the index."""
    try:
        index = _load_or_create_index(CONTENT_INDEX_PATH)
        if index is None:
            return False

        vector = embed([text])  # (1, 384)
        # turbovec search takes 2D array of queries, returns (scores, indices)
        scores, _ = index.search(vector, k=1)
        if scores is not None and len(scores) > 0 and scores.shape[1] > 0:
            best_score = float(scores[0, 0])
            # turbovec returns raw dot-product / distance scores.
            # Normalised embeddings → score ≈ cosine similarity.
            return best_score >= threshold
        return False
    except Exception:
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


def rebuild_content_index() -> None:
    """Rebuild the content index from scratch (useful for cache cleanup)."""
    try:
        if os.path.exists(CONTENT_INDEX_PATH):
            os.remove(CONTENT_INDEX_PATH)
    except Exception:
        logger.error("Failed to rebuild content index", exc_info=True)

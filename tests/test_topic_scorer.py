"""Tests for topic_scorer.py -- vector_store calls are mocked (no ML deps needed)."""
import pytest

import topic_scorer
from topic_scorer import score_topic, pick_best_topics


class TestScoreTopic:
    def test_full_engagement_no_africa_context(self, monkeypatch):
        monkeypatch.setattr(topic_scorer, "get_africa_context", lambda text, k=3: [])
        score = score_topic({"engagement_score": 1000, "synthesis": "big global story"})
        assert score == pytest.approx(0.95)

    def test_zero_engagement_no_africa_context(self, monkeypatch):
        monkeypatch.setattr(topic_scorer, "get_africa_context", lambda text, k=3: [])
        score = score_topic({"engagement_score": 0, "synthesis": "quiet story"})
        assert score == 0.0

    def test_africa_context_adds_bonus(self, monkeypatch):
        monkeypatch.setattr(topic_scorer, "get_africa_context", lambda text, k=3: ["a", "b", "c"])
        score = score_topic({"engagement_score": 0, "synthesis": "naira story"})
        assert score == pytest.approx(0.05)

    def test_engagement_scales_linearly_below_1000(self, monkeypatch):
        monkeypatch.setattr(topic_scorer, "get_africa_context", lambda text, k=3: [])
        score = score_topic({"engagement_score": 500, "synthesis": "medium story"})
        assert score == pytest.approx(0.475)

    def test_africa_context_failure_does_not_crash(self, monkeypatch):
        def boom(text, k=3):
            raise RuntimeError("index unavailable")

        monkeypatch.setattr(topic_scorer, "get_africa_context", boom)
        score = score_topic({"engagement_score": 1000, "synthesis": "story"})
        assert score == pytest.approx(0.95)  # africa_bonus falls back to 0.0


class TestPickBestTopics:
    def test_filters_duplicates(self, monkeypatch):
        monkeypatch.setattr(topic_scorer, "is_duplicate", lambda text: text == "dup")
        monkeypatch.setattr(topic_scorer, "get_africa_context", lambda text, k=3: [])

        results = [
            {"synthesis": "dup", "engagement_score": 900},
            {"synthesis": "fresh", "engagement_score": 500},
        ]
        picked = pick_best_topics(results, max_picks=5)
        assert len(picked) == 1
        assert picked[0]["synthesis"] == "fresh"

    def test_sorts_by_score_descending(self, monkeypatch):
        monkeypatch.setattr(topic_scorer, "is_duplicate", lambda text: False)
        monkeypatch.setattr(topic_scorer, "get_africa_context", lambda text, k=3: [])

        results = [
            {"synthesis": "low", "engagement_score": 100},
            {"synthesis": "high", "engagement_score": 900},
        ]
        picked = pick_best_topics(results, max_picks=5)
        assert [r["synthesis"] for r in picked] == ["high", "low"]

    def test_respects_max_picks(self, monkeypatch):
        monkeypatch.setattr(topic_scorer, "is_duplicate", lambda text: False)
        monkeypatch.setattr(topic_scorer, "get_africa_context", lambda text, k=3: [])

        results = [{"synthesis": f"story{i}", "engagement_score": i * 100} for i in range(5)]
        picked = pick_best_topics(results, max_picks=2)
        assert len(picked) == 2

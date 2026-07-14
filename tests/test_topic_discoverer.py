"""Tests for topic_discoverer.py -- pure regex/scoring logic, no network calls."""
from topic_discoverer import TopicDiscoverer as TD


class TestCleanHeadline:
    def test_strips_publication_suffix(self):
        assert TD._clean_headline("Bitcoin hits new high - Reuters") == "Bitcoin hits new high"

    def test_strips_domain_suffix(self):
        assert TD._clean_headline("Fed holds rates - group.bnpparibas") == "Fed holds rates"

    def test_collapses_whitespace(self):
        assert TD._clean_headline("Markets   rally    hard") == "Markets rally hard"


class TestLooksTruncated:
    def test_empty_string_is_truncated(self):
        assert TD._looks_truncated("") is True

    def test_starts_with_colon_is_truncated(self):
        assert TD._looks_truncated(": Trump dismisses claims") is True

    def test_ends_with_preposition_is_truncated(self):
        assert TD._looks_truncated("Bitcoin surges to the") is True

    def test_ends_with_recognised_peak_word_not_truncated(self):
        assert TD._looks_truncated("Markets reach three-year high") is False


class TestScoreRelevance:
    def test_no_keywords_scores_low(self):
        assert TD._score_relevance("The quick brown fox jumps over the lazy dog") == 0.2

    def test_single_keyword_match(self):
        assert TD._score_relevance("Stock reaches $50 billion valuation milestone") == 0.6

    def test_two_keyword_matches(self):
        assert TD._score_relevance("Bitcoin hits new all time high") == 0.8

    def test_three_plus_keyword_matches_caps_at_one(self):
        score = TD._score_relevance("Federal Reserve holds rates steady amid inflation concerns")
        assert score == 1.0


class TestStemWord:
    def test_strips_ing_suffix(self):
        assert TD._stem_word("running") == "runn"

    def test_strips_s_suffix(self):
        assert TD._stem_word("rates") == "rate"

    def test_short_word_unchanged(self):
        assert TD._stem_word("oil") == "oil"


class TestWordOverlap:
    def test_high_overlap_for_similar_headlines(self):
        overlap = TD._word_overlap(
            "Bitcoin price surges to new high",
            "Bitcoin price surges past record",
        )
        assert overlap > 0.5

    def test_low_overlap_for_unrelated_headlines(self):
        overlap = TD._word_overlap(
            "Bitcoin price surges",
            "Oil prices drop today",
        )
        assert overlap < 0.3


class TestHeadlineToTopic:
    def test_bitcoin_headline_with_specific_detail(self):
        result = TD._headline_to_topic("Bitcoin hits all-time high as ETF inflows surge")
        assert "Bitcoin" in result

    def test_generic_fed_headline_uses_template(self):
        result = TD._headline_to_topic("Fed holds rates steady but signals cautious stance")
        assert result == "US Federal Reserve interest rates dot plot"

    def test_unrecognised_headline_falls_back_to_cleaned_text(self):
        result = TD._headline_to_topic("Random unrelated headline about nothing specific here")
        assert "Random" in result


class TestExtractTopics:
    def test_filters_short_and_non_news_headlines(self):
        headlines = [
            {"title": "Short", "source": "test"},  # too short
            {"title": "Complete guide to how bitcoin mining works explained", "source": "test"},  # non-news
            {"title": "Federal Reserve signals rate cut amid slowing inflation data", "source": "test"},
        ]
        topics = TD._extract_topics(headlines)
        assert len(topics) == 1
        assert "Federal Reserve" in topics[0]["headline"]

    def test_deduplicates_exact_titles(self):
        headline = "Federal Reserve signals rate cut amid slowing inflation data"
        headlines = [{"title": headline, "source": "a"}, {"title": headline, "source": "b"}]
        topics = TD._extract_topics(headlines)
        assert len(topics) == 1


class TestRankTopics:
    def test_deduplicates_by_cluster(self):
        topics = [
            {"headline": "Bitcoin surges past sixty thousand dollars today", "query": "q1", "relevance": 1.0, "source": "a", "upvotes": 0, "origin": "x"},
            {"headline": "Bitcoin price action continues higher this week", "query": "q2", "relevance": 0.9, "source": "b", "upvotes": 0, "origin": "x"},
        ]
        ranked = TD._rank_topics(topics)
        assert len(ranked) == 1
        assert ranked[0]["query"] == "q1"  # higher relevance kept

    def test_keeps_distinct_clusters(self):
        topics = [
            {"headline": "Bitcoin surges past sixty thousand dollars today", "query": "q1", "relevance": 1.0, "source": "a", "upvotes": 0, "origin": "x"},
            {"headline": "Gold prices rally on safe haven demand today", "query": "q2", "relevance": 1.0, "source": "b", "upvotes": 0, "origin": "x"},
        ]
        ranked = TD._rank_topics(topics)
        assert len(ranked) == 2

"""Tests for humanizer.py."""
from humanizer import humanize, _strip_filler, _enforce_short_paragraphs


class TestStripFiller:
    def test_removes_known_ai_filler_phrases(self):
        text = "Let's dive in and delve into the landscape of markets."
        result = _strip_filler(text)
        assert "dive in" not in result.lower()
        assert "delve into" not in result.lower()
        assert "landscape" not in result.lower()

    def test_case_insensitive_removal(self):
        result = _strip_filler("It Is Important To note this.")
        assert "it is important to" not in result.lower()

    def test_collapses_excess_blank_lines(self):
        result = _strip_filler("Para one.\n\n\n\nPara two.")
        assert "\n\n\n" not in result

    def test_leaves_normal_text_untouched(self):
        text = "Bitcoin rallied sharply this week on strong ETF inflows."
        assert _strip_filler(text) == text


class TestEnforceShortParagraphs:
    def test_short_paragraph_untouched(self):
        text = "A short paragraph."
        assert _enforce_short_paragraphs(text, max_len=120) == text

    def test_long_paragraph_gets_split(self):
        long_para = "This is sentence one. " * 10  # well over 120 chars
        result = _enforce_short_paragraphs(long_para.strip(), max_len=120)
        assert "\n" in result


class TestHumanize:
    def test_applies_both_passes(self):
        text = "Let's dive in. " + ("This is a long sentence about markets. " * 5)
        result = humanize(text)
        assert "dive in" not in result.lower()

    def test_returns_original_on_internal_failure(self, monkeypatch):
        import humanizer

        def boom(text):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(humanizer, "_strip_filler", boom)
        original = "Some original text."
        assert humanize(original) == original

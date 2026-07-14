"""Tests for telegram_bot.py."""
from telegram_bot import _split_html_safe, send_message


class TestSplitHtmlSafe:
    def test_short_text_returns_single_chunk(self):
        assert _split_html_safe("hello world") == ["hello world"]

    def test_long_text_splits_within_limit(self):
        text = ("line " * 10 + "\n") * 300
        chunks = _split_html_safe(text, max_len=100)
        assert len(chunks) > 1
        assert all(len(c) <= 100 for c in chunks)

    def test_splits_preserve_content(self):
        text = ("line " * 10 + "\n") * 300
        chunks = _split_html_safe(text, max_len=100)
        rejoined = "".join(chunks)
        assert rejoined.replace(" ", "").replace("\n", "") == text.replace(" ", "").replace("\n", "")

    def test_does_not_split_inside_open_html_tag(self):
        # Build text where a naive split at max_len would land inside a <b> tag
        text = "word " * 19 + "<b>bold text here</b> " + "word " * 20
        chunks = _split_html_safe(text, max_len=100)
        for chunk in chunks:
            assert chunk.count("<") == chunk.count(">")


class TestSendMessage:
    def test_returns_true_on_success(self, monkeypatch):
        import telegram_bot

        class FakeResponse:
            def raise_for_status(self):
                pass

        monkeypatch.setattr(telegram_bot.requests, "post", lambda *a, **k: FakeResponse())
        assert send_message("hello") is True

    def test_returns_false_on_request_failure(self, monkeypatch):
        import telegram_bot

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(telegram_bot.requests, "post", boom)
        assert send_message("hello") is False

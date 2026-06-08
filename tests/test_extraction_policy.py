"""
Tests for the extractor entry point (pipeline/extractor/__init__.py): routing,
Unicode normalization, and the low-yield policy helpers.
"""

import pytest

from pipeline import extractor
from pipeline.extractor import extract_text, is_low_yield, usable_char_count


class TestLowYield:
    def test_empty(self):
        assert is_low_yield("")

    def test_whitespace_only(self):
        assert is_low_yield("   \n\t  ")

    def test_short_text(self):
        assert is_low_yield("abc 123")  # 6 alnum < 40

    def test_real_text(self):
        assert not is_low_yield("word " * 20)  # 80 alnum

    def test_usable_char_count_counts_only_alnum(self):
        assert usable_char_count("a1 b2 !! -,") == 4

    def test_custom_threshold(self):
        assert is_low_yield("abcd", min_chars=10)
        assert not is_low_yield("abcd", min_chars=3)


class TestRouting:
    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError):
            extract_text("file.txt", b"hello")

    def test_no_extension_raises(self):
        with pytest.raises(ValueError):
            extract_text("file", b"hello")

    def test_routes_pdf(self, monkeypatch):
        monkeypatch.setattr(extractor, "_extract_pdf", lambda b: "PDFTEXT")
        assert extract_text("x.pdf", b"x") == "PDFTEXT"

    def test_clean_unicode_applied(self, monkeypatch):
        # Replacement char � should be normalised (clean_unicode -> em-dash).
        monkeypatch.setattr(extractor, "_extract_docx", lambda b: "A�B")
        out = extract_text("x.docx", b"x")
        assert "�" not in out
        assert out == "A—B"

    def test_raises_only_on_true_parse_failure(self):
        # Invalid docx bytes (not a zip) => python-docx raises => propagates.
        with pytest.raises(Exception):
            extract_text("bad.docx", b"this is not a docx")

    def test_empty_result_not_an_error(self, monkeypatch):
        # An empty extraction is returned as "", NOT raised — the caller's
        # low-yield policy decides what to do with it.
        monkeypatch.setattr(extractor, "_extract_docx", lambda b: "")
        assert extract_text("x.docx", b"x") == ""

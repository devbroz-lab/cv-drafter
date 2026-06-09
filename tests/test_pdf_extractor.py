"""
Tests for the pdfplumber-based PDF extractor (pipeline/extractor/pdf_extractor.py):
[PAGE]/[TABLE] tagging (DOCX parity), low-yield detection, and the pypdf fallback.
"""

from pathlib import Path

import pytest

from pipeline.extractor import extract_text, is_low_yield
from pipeline.extractor import pdf_extractor as pe

SAMPLE = Path(__file__).parent / "sample_files"


class TestSamplePdf:
    def test_text_and_table_tags(self):
        b = (SAMPLE / "sample_cv.pdf").read_bytes()
        t = extract_text("sample_cv.pdf", b)
        assert "[PAGE 1]" in t
        assert "[TABLE 1]" in t and "[END TABLE]" in t
        assert "Name | Jane Doe" in t
        assert not is_low_yield(t)

    def test_blank_pdf_is_low_yield(self):
        b = (SAMPLE / "blank.pdf").read_bytes()
        t = extract_text("blank.pdf", b)
        assert is_low_yield(t)


class TestRowToLine:
    def test_trims_trailing_and_joins(self):
        assert pe._row_to_line(["a", "b", "", ""]) == "a | b"
        assert pe._row_to_line(["", ""]) == ""
        assert pe._row_to_line(["x\n y", None, "z"]) == "x  y |  | z"


class TestFallback:
    def test_pdfplumber_error_falls_back_to_pypdf(self, monkeypatch):
        monkeypatch.setattr(
            pe, "_pdfplumber_text", lambda b: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        monkeypatch.setattr(pe, "_pypdf_text", lambda b: "FALLBACK")
        assert pe.extract_text_from_bytes(b"x") == "FALLBACK"

    def test_pdfplumber_empty_falls_back_to_pypdf(self, monkeypatch):
        monkeypatch.setattr(pe, "_pdfplumber_text", lambda b: "")
        monkeypatch.setattr(pe, "_pypdf_text", lambda b: "RECOVERED")
        assert pe.extract_text_from_bytes(b"x") == "RECOVERED"

    def test_both_empty_returns_empty(self, monkeypatch):
        monkeypatch.setattr(pe, "_pdfplumber_text", lambda b: "")
        monkeypatch.setattr(pe, "_pypdf_text", lambda b: "")
        assert pe.extract_text_from_bytes(b"x") == ""

    def test_empty_bytes_raises(self):
        with pytest.raises(ValueError):
            pe.extract_text_from_bytes(b"")

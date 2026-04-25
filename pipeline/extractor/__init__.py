"""Unified text extraction entry point — routes to docx or pdf by file extension."""

from __future__ import annotations

from pipeline.extractor.docx_extractor import extract_text_from_bytes as _extract_docx
from pipeline.extractor.pdf_extractor import extract_text_from_bytes as _extract_pdf


def extract_text(filename: str, file_bytes: bytes) -> str:
    """Extract tagged plain text from a CV file. Routes by extension."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "docx":
        return _extract_docx(file_bytes)
    if suffix == "pdf":
        return _extract_pdf(file_bytes)
    raise ValueError(f"Unsupported file type: .{suffix}")

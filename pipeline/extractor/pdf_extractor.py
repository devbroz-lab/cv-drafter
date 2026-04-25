"""Extract text from .pdf files."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


def extract_text_from_bytes(file_bytes: bytes) -> str:
    if not file_bytes:
        raise ValueError("PDF payload is empty")

    reader = PdfReader(BytesIO(file_bytes))
    pages: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(text)

    return "\n\n".join(pages).strip()

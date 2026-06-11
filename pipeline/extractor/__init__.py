"""Unified text extraction entry point — routes to docx or pdf by file extension.

``extract_text`` returns the best-effort tagged text and raises only on a true
parse failure (corrupt / unreadable file), never on "the document had no text".
Whether empty/low-yield text should halt the pipeline is a caller policy
decision — use ``is_low_yield`` for that (see ``pipeline.orchestrator``).
"""

from __future__ import annotations

from pipeline.extractor.docx_extractor import extract_text_from_bytes as _extract_docx
from pipeline.extractor.pdf_extractor import extract_text_from_bytes as _extract_pdf
from pipeline.utils._helpers import clean_unicode

# Minimum alphanumeric characters for extraction to count as "usable" text.
# Below this, the document is treated as having produced nothing (scanned /
# image-only PDF, empty or near-empty file).
_MIN_USABLE_ALNUM_CHARS = 40


def extract_text(filename: str, file_bytes: bytes) -> str:
    """Extract tagged plain text from a CV/ToR file. Routes by extension and
    normalises Unicode (fixes encoding replacement chars / ligatures)."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "docx":
        text = _extract_docx(file_bytes)
    elif suffix == "pdf":
        text = _extract_pdf(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: .{suffix}")
    return str(clean_unicode(text or ""))


def usable_char_count(text: str) -> int:
    """Count alphanumeric characters — the signal for 'real' extracted content
    (ignores whitespace and structural punctuation/tags)."""
    return sum(1 for ch in (text or "") if ch.isalnum())


def is_low_yield(text: str, min_chars: int = _MIN_USABLE_ALNUM_CHARS) -> bool:
    """True when extraction produced no usable text (empty / scanned / corrupt)."""
    return usable_char_count(text) < min_chars

"""Extract text from .pdf files with the same structural tags as the DOCX path.

Primary engine is **pdfplumber** (layout-aware text + real table extraction), so
PDFs and DOCX give Agent 1 a comparable ``[PAGE]`` / ``[TABLE]`` tagged
rendering. If pdfplumber is unavailable or errors on a document, it falls back
to **pypdf**'s plain text dump — a pdfplumber failure never regresses a file
that pypdf can read.

Both libraries are imported lazily inside the functions so that importing
``pipeline.extractor`` (e.g. for the DOCX path) never requires the PDF stack.
"""

from __future__ import annotations

import logging
from io import BytesIO

log = logging.getLogger(__name__)


def _row_to_line(row) -> str:
    """Render one extracted table row as a ``" | "``-joined line (DOCX parity)."""
    cells = [(c or "").strip().replace("\n", " ") for c in row]
    while cells and not cells[-1]:  # trim trailing empties, keep internal alignment
        cells.pop()
    return " | ".join(cells) if cells else ""


def _pdfplumber_text(file_bytes: bytes) -> str:
    """Layout-aware extraction. Table regions are emitted as ``[TABLE n]`` blocks
    and the remaining (non-table) text is emitted separately, so table content is
    not duplicated as loose text."""
    import pdfplumber

    chunks: list[str] = []
    table_index = 0
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            page_chunks: list[str] = []

            try:
                tables = page.find_tables() or []
            except Exception:
                tables = []
            bboxes = [t.bbox for t in tables]

            def _outside_tables(obj, _bboxes=bboxes) -> bool:
                cx = (obj.get("x0", 0) + obj.get("x1", 0)) / 2
                cy = (obj.get("top", 0) + obj.get("bottom", 0)) / 2
                return not any(
                    x0 <= cx <= x1 and top <= cy <= bottom
                    for (x0, top, x1, bottom) in _bboxes
                )

            # Non-table text (reading order).
            try:
                source = page.filter(_outside_tables) if bboxes else page
                text = (source.extract_text() or "").strip()
            except Exception:
                try:
                    text = (page.extract_text() or "").strip()
                except Exception:
                    text = ""
            if text:
                page_chunks.append(text)

            # Tables as structured rows.
            for tbl in tables:
                try:
                    rows = tbl.extract() or []
                except Exception:
                    rows = []
                lines = [_row_to_line(r) for r in rows]
                lines = [ln for ln in lines if ln]
                if lines:
                    table_index += 1
                    page_chunks.append(f"[TABLE {table_index}]")
                    page_chunks.extend(lines)
                    page_chunks.append("[END TABLE]")

            if page_chunks:
                chunks.append(f"[PAGE {page_no}]")
                chunks.extend(page_chunks)

    return "\n".join(chunks).strip()


def _pypdf_text(file_bytes: bytes) -> str:
    """Fallback: pypdf plain text dump, with page markers."""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(file_bytes))
    pages: list[str] = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"[PAGE {page_no}]\n{text}")
    return "\n\n".join(pages).strip()


def extract_text_from_bytes(file_bytes: bytes) -> str:
    if not file_bytes:
        raise ValueError("PDF payload is empty")

    # Try pdfplumber first; fall back to pypdf on any error OR when pdfplumber
    # parses but finds no text (e.g. scanned/image-only PDF — pypdf may still
    # recover embedded text). If both yield nothing, return "" and let the
    # caller's low-yield policy decide (fail fast with a clear message).
    try:
        text = _pdfplumber_text(file_bytes)
        if text:
            return text
        log.info("pdfplumber found no text; trying pypdf fallback")
    except Exception as exc:
        log.warning("pdfplumber failed (%s); falling back to pypdf", exc)

    try:
        return _pypdf_text(file_bytes)
    except Exception as exc:
        raise ValueError(f"Could not read PDF: {exc}") from exc

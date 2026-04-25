"""Extract text from .docx files with structural tags for the AI pipeline."""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


def _extract_table_rows(tbl_element) -> list[str]:
    """Extract table rows directly from XML.

    This handles normal cells and Word content controls (`w:sdt`) that
    `python-docx` sometimes hides from `row.cells`, such as the first-name /
    family-name rows in some donor CV templates.
    """
    rows: list[str] = []
    tr_tag = qn("w:tr")
    tc_tag = qn("w:tc")
    sdt_tag = qn("w:sdt")
    sdt_content_tag = qn("w:sdtContent")
    p_tag = qn("w:p")
    text_tag = qn("w:t")

    for tr in tbl_element.iterchildren(tag=tr_tag):
        cell_values: list[str] = []
        tc_nodes = []
        for child in tr.iterchildren():
            if child.tag == tc_tag:
                tc_nodes.append(child)
            elif child.tag == sdt_tag:
                for sdt_child in child.iterchildren():
                    if sdt_child.tag != sdt_content_tag:
                        continue
                    for content_child in sdt_child.iterchildren():
                        if content_child.tag == tc_tag:
                            tc_nodes.append(content_child)

        for tc in tc_nodes:
            para_texts: list[str] = []
            for p in tc.iter(p_tag):
                runs = [t.text for t in p.iter(text_tag) if t.text]
                line = "".join(runs).strip()
                if line:
                    para_texts.append(line)
            val = "\n".join(para_texts)
            if val:
                cell_values.append(val)
        if cell_values:
            rows.append(" | ".join(cell_values))
    return rows


def extract_text_from_bytes(file_bytes: bytes) -> str:
    if not file_bytes:
        raise ValueError("DOCX payload is empty")

    document = Document(BytesIO(file_bytes))
    chunks: list[str] = []
    table_index = 0

    for child in document.element.body:
        # Strip namespace prefix to get bare tag name
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            para = Paragraph(child, document)
            text = para.text.strip()
            if not text:
                continue
            style_name = (para.style.name or "").lower()
            if "heading" in style_name or "title" in style_name:
                chunks.append(f"[HEADING] {text}")
            elif any(run.bold for run in para.runs if run.text.strip()):
                chunks.append(f"[BOLD] {text}")
            else:
                chunks.append(f"[NORMAL] {text}")

        elif tag == "tbl":
            table_index += 1
            chunks.append(f"[TABLE {table_index}]")
            for row_text in _extract_table_rows(child):
                chunks.append(row_text)
            chunks.append("[END TABLE]")

    return "\n".join(chunks).strip()

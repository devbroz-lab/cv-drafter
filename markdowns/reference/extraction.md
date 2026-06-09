---
title: Text Extraction (DOCX & PDF)
type: reference
status: current
owner: backend
last_verified: 2026-06-08
code_refs:
  - pipeline/extractor/__init__.py
  - pipeline/extractor/docx_extractor.py
  - pipeline/extractor/pdf_extractor.py
  - pipeline/utils/_helpers.py
related:
  - reference/orchestration.md
  - reference/agents/a1-cv-extractor.md
  - design/0002-pdfplumber-extraction-hardening.md
---

# Text Extraction

The first, deterministic step: turn an uploaded CV/ToR (`.docx` or `.pdf`) into the **tagged plain
text** fed to A1/A2. This is the lens the LLM sees the document through, so its fidelity bounds
everything downstream.

## Entry point

`pipeline.extractor.extract_text(filename, file_bytes) -> str` routes by extension (`.docx`/`.pdf`;
anything else raises `ValueError`), then normalises the result with `clean_unicode`
(`pipeline/utils/_helpers.py`) to repair encoding artifacts. It returns best-effort text and **raises
only on a true parse failure** — never on "the document had no text".

The package also exposes the low-yield policy helpers:
- `usable_char_count(text)` — count of alphanumeric characters (the "real content" signal).
- `is_low_yield(text, min_chars=40)` — `True` when extraction produced no usable text.

The orchestrator owns the *policy* (`reference/orchestration.md`): a CV that fails to parse, or is
low-yield, fails Phase 1 fast with a recruiter-friendly message; a low-yield ToR is a non-fatal warning.

## Tag vocabulary (shared by both formats)

Extraction emits lightly *tagged* text so A1 gets structural cues without a full layout engine:

| Tag | Meaning |
|-----|---------|
| `[HEADING]` / `[BOLD]` / `[NORMAL]` | paragraph class (DOCX) |
| `- ` prefix | list item (DOCX `w:numPr`) |
| `[TABLE n]` … rows … `[END TABLE]` | a table; rows are `" | "`-joined cells |
| `[HEADER]…[/HEADER]` / `[FOOTER]…[/FOOTER]` | DOCX header/footer block |
| `[PAGE n]` | PDF page boundary |

## DOCX (`docx_extractor.py`)

Built on `python-docx`. Walks the body's top-level paragraphs and tables in document order, plus:

- **Headers & footers** via the section API (often carry the candidate name/contact).
- **Hyperlink / field / text-box text** — uses a recursive `w:t` gather (`_para_text`) instead of
  `Paragraph.text`, which drops those runs.
- **Lists** — `w:numPr` paragraphs get a `- ` prefix.
- **Merged cells** — `w:gridSpan` is padded with empty placeholder columns so rows stay aligned.
- **Content controls** — `w:sdt`-wrapped cells (hidden from `row.cells`) are recovered.
- **Resilience** — each paragraph/table is isolated in try/except; one malformed element is skipped,
  not fatal. (A paragraph with no resolvable style — common in non-Word `.docx` — does not crash.)

## PDF (`pdf_extractor.py`)

Primary engine is **pdfplumber** (layout-aware text + real table extraction, emitting the same
`[PAGE]`/`[TABLE]` tags as DOCX for parity). Table regions are separated from loose text so cells
aren't duplicated. If pdfplumber errors or finds no text, it **falls back to pypdf**'s plain dump.
Both libraries are imported lazily, so importing `pipeline.extractor` never requires the PDF stack.
No OCR: a scanned/image-only PDF yields no text → caught by the low-yield policy.

## Contracts & invariants

- `extract_text` raises only on parse failure; empty output is returned as `""`.
- DOCX and PDF produce the **same tag vocabulary** — A1's prompt rules (tables, merged cells) apply
  regardless of source format.
- Output is always `clean_unicode`-normalised.

## Gotchas

- pdfplumber table detection is line-based; borderless "tables" may be missed (text still captured).
- DOCX list detection covers direct `w:numPr` only — list styles that carry numbering in the style
  definition aren't dash-prefixed (text is still captured).
- `.doc` / `.rtf` / `.odt` are unsupported (raise `ValueError`).

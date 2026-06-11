---
title: 0002 — Extraction hardening (DOCX robustness + pdfplumber + fail-fast)
type: design
status: accepted
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/extractor/docx_extractor.py
  - pipeline/extractor/pdf_extractor.py
  - pipeline/extractor/__init__.py
  - pipeline/orchestrator.py
  - requirements.in
related:
  - reference/extraction.md
---

# 0002 — Extraction hardening (DOCX robustness + pdfplumber + fail-fast)

## Context

The initial parsing step was brittle. The DOCX extractor crashed on valid non-Word `.docx` files
(`para.style.name` where `para.style` is `None` — common in Google-Docs/LibreOffice/pandoc exports;
one real file had this on 83/151 paragraphs), and the unguarded CV-extract call in `run_phase1`
turned it into a generic `failed`. It also dropped content (headers/footers, hyperlinks, text boxes,
list markers) and mishandled merged cells. The PDF path was a naive `pypdf` text dump: no tables, no
layout, and a scanned/image PDF returned `""` silently and fed an empty CV to A1. DOCX and PDF gave
A1 very different inputs (format asymmetry).

## Decision

- **DOCX:** guard `para.style is None`; isolate each paragraph/table in try/except; capture
  headers/footers, hyperlink/field/text-box text (recursive `w:t` gather), list markers (`w:numPr`),
  and merged-cell column alignment (`w:gridSpan`).
- **PDF:** rewrite on **pdfplumber** (layout-aware text + real tables, emitting the same
  `[PAGE]`/`[TABLE]` tags as DOCX), with a **pypdf fallback**; import both lazily.
- **Policy:** normalise output with `clean_unicode`; add `is_low_yield`; `run_phase1` now creates the
  manifest first, guards CV extraction, and **fails fast with a clear message** on parse failure or
  low-yield CV (with a manifest warning). ToR is best-effort. No OCR; no new input formats.

## Consequences

**Good:** the reported file processes; both formats give A1 comparable structure; failures are clear
and surfaced as warnings on `/manifest`; no empty-CV Opus calls.
**Bad/cost:** new dependency `pdfplumber` (pulls `pdfminer-six`, `pillow`) — pure-Python, no system
binaries; pdfplumber is heavier than pypdf and its borderless-table detection is imperfect;
scanned/image PDFs remain unsupported (by design — they fail fast).

## Alternatives considered

- Keep pypdf + add robustness only — rejected (loses table/layout structure for PDFs).
- pdfplumber + OCR fallback for scanned PDFs — deferred (adds Tesseract/poppler system deps + deploy
  changes).
- Continue-and-warn instead of fail-fast on empty text — rejected (wastes an Opus A1 call and
  hallucinates from nothing).

## Refs

Branch `fix/opus48-oversized-output-lean-agents`. Tests: `tests/test_docx_extractor.py`,
`tests/test_pdf_extractor.py`, `tests/test_extraction_policy.py`; fixtures in `tests/sample_files/`.

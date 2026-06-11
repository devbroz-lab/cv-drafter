---
title: Documentation Index
type: meta
status: current
owner: backend
last_verified: 2026-06-11
code_refs: []
related: [CONVENTIONS.md]
---

# Documentation Index

The front door to `cv-drafter` docs. Read `CONVENTIONS.md` for how this is organised. Every doc is
registered below; if it's not here, it doesn't count.

## Start here
- New to the pipeline → [reference/pipeline-overview.md](reference/pipeline-overview.md)
- Doc conventions → [CONVENTIONS.md](CONVENTIONS.md)

## Reference — current-state truth

| Doc | Covers | Owner | Status |
|-----|--------|-------|--------|
| [reference/pipeline-overview.md](reference/pipeline-overview.md) | Phases, agents, checkpoints, end-to-end data flow, stack | backend | current |
| [reference/data-model.md](reference/data-model.md) | `CVData`, `DistilledToR`, `FormatProfile`, output blocks | backend | current |
| [reference/extraction.md](reference/extraction.md) | DOCX/PDF text extraction, tags, low-yield policy | backend | current |
| [reference/orchestration.md](reference/orchestration.md) | Phases, status machine, manifest (progress/warnings) | backend | current |
| [reference/artifacts.md](reference/artifacts.md) | Run-dir JSON contracts (produced-by / consumed-by) | backend | current |
| [reference/renderer.md](reference/renderer.md) | GIZ/WB renderers, dynamic template, what each donor shows | backend | current |
| [reference/api.md](reference/api.md) | HTTP surface, response models, status machine | backend | current |

### Agents (one per `pipeline/agents/*.py`)

| Doc | Agent | Status |
|-----|-------|--------|
| [reference/agents/a1-cv-extractor.md](reference/agents/a1-cv-extractor.md) | A1 CV Extractor (Opus) | current |
| [reference/agents/a2-tor-summarizer.md](reference/agents/a2-tor-summarizer.md) | A2 ToR Summarizer | current |
| [reference/agents/a3-cv-tor-mapper.md](reference/agents/a3-cv-tor-mapper.md) | A3 CV–ToR Mapper | current |
| [reference/agents/a4-fields-generator.md](reference/agents/a4-fields-generator.md) | A4 Fields Generator | current |
| [reference/agents/a5-content-reviewer.md](reference/agents/a5-content-reviewer.md) | A5 Content Reviewer | current |
| [reference/agents/a6-compressor.md](reference/agents/a6-compressor.md) | A6 Compressor | current |
| [reference/agents/a7-field-editor.md](reference/agents/a7-field-editor.md) | A7 Field Editor (post-completion) | current |

## Design — ADRs (immutable history)

| ADR | Decision | Status |
|-----|----------|--------|
| [design/0001-lean-agent-output-contracts.md](design/0001-lean-agent-output-contracts.md) | Lean agent contracts + parse-failure recovery (Opus-4.8 oversized output) | accepted |
| [design/0002-pdfplumber-extraction-hardening.md](design/0002-pdfplumber-extraction-hardening.md) | Extraction hardening (DOCX robustness + pdfplumber + fail-fast) | accepted |
| [design/0003-manifest-progress-warnings.md](design/0003-manifest-progress-warnings.md) | Real-time progress & warnings on the polled `/manifest` | accepted |
| [design/0004-empty-field-review-flags-countries-derivation-and-render-placeholders.md](design/0004-empty-field-review-flags-countries-derivation-and-render-placeholders.md) | Empty-field review flags, countries derivation, render placeholders, `other_skills`→str | accepted |

## Frontend — consumer contracts

| Doc | Covers | Owner | Status |
|-----|--------|-------|--------|
| [frontend/progress-and-warnings.md](frontend/progress-and-warnings.md) | Consuming progress + warnings from `/manifest` | frontend | current |

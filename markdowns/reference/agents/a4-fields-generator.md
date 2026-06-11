---
title: A4 — Fields Generator
type: reference
status: current
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/agents/fields_generator.py
  - pipeline/validators.py
  - pipeline/utils/llm.py
  - models.py
related:
  - reference/renderer.md
  - reference/data-model.md
  - design/0001-lean-agent-output-contracts.md
---

# A4 — Fields Generator

The first agent that writes new content: generates the donor-specific fields and fills a few derived
fields. Phase 3.

- **Model:** Sonnet (`ANTHROPIC_SYNTHESIS_MODEL`) — the sole generative-synthesis agent.
- **Input:** `mapped_cv.json` + `tor_data.json` + `<format_profile>` + `<params>`.
- **Output:** `generated_fields.json` (initial write: `generated`, `generation_warnings`, `review:null`,
  `compression:null`).
- **Manifest step:** `fields_generator`.

## Output contract — a PATCH (no CVData echo)

A4 returns a small patch, not the CVData:
```
{ generated_fields:[{field_key, content, source}],
  present_position:"<optional>",
  project_overviews:[{index, main_project_features}],
  generation_warnings:[] }
```
`fields_generator.run` merges the patch into the mapped `CVData` (set `generated_fields`, fill
`present_position` if empty, apply project overviews), then validates and writes. This keeps A4's
output small no matter how rich the input (see `design/0001-lean-agent-output-contracts.md`).

## What it generates

`FormatProfile.generative_field_keys` selects the content:
- **GIZ → `key_qualifications`** — tailored qualification bullets (≤25 words, noun/stat-led,
  candidate-anchored, grounded in CV evidence).
- **WB → `detailed_tasks`** — forward-looking task statements (≤30 words) derived from the ToR.

**Minimum output guarantee:** at least one non-empty entry per generative key, always — an empty
`content` halts the pipeline at the post-A4 validator.

## Donor-aware project narrative (`project_overviews`)

- **GIZ:** the renderer shows only `main_project_features` for projects, so A4 writes a full ~50–90
  word narrative (project context + the candidate's role/contributions) for **every** kept project,
  and the merge **overwrites** the terse extraction.
- **WB:** `main_project_features` and `activities_performed` render separately, so A4 only **fills**
  an empty `main_project_features` (never overwrites/merges).

## Contracts & invariants

- LLM call via `call_agent_json` with a `reduce_input` (trims project text on failure).
- After A4, the orchestrator runs `validate_fields_generator_output` (`pipeline/validators.py`): if
  every `generated_fields[].content` is empty, Phase 3 hard-fails before A5/A6.
- Duration/year are pre-computed upstream (A3) — A4 does not recompute them.

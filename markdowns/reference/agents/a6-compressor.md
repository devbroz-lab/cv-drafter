---
title: A6 — Compressor
type: reference
status: current
owner: backend
last_verified: 2026-06-11
code_refs:
  - pipeline/agents/compressor.py
  - pipeline/precompute_utils.py
  - pipeline/utils/paths.py
  - templates/registry.py
related:
  - reference/renderer.md
  - reference/data-model.md
  - design/0001-lean-agent-output-contracts.md
---

# A6 — Compressor

Shortens the compressible CVData fields to fit the page-limit target. Protected fields are never
touched. Phase 3 (final step before checkpoint 3).

- **Model:** Sonnet (`ANTHROPIC_MODEL`).
- **Input:** `generated_fields.json["generated"]` + `tor_data.json` + `<compression_params>`.
- **Output:** updates `generated_fields.json` in place — `compression` block + compressed `generated`.
- **Manifest step:** `compressor`.

## Target & skip

The orchestrator passes `target_words` from `get_compression_params` (`templates/registry.py`):
`page_limit × words_per_page`. A6 pre-computes the current compressible word count in Python; if
already at/under target it **skips the LLM** and writes a `compression` block with `applied: false`.

## Output contract — a PATCH (no CVData echo)

A6 returns:
```
{ compression: { applied, words_before, words_after, target_words,
                 ratio_applied, target_not_reached, fields_shortened[] },
  compressed_fields: [{ path, content }],
  generation_warnings: [] }
```
`compressor.run` applies each `compressed_fields` entry (`content → path`) onto a copy of the
pre-compression data via the shared setter (`pipeline/utils/paths.set_by_path`), recomputes the
authoritative `words_after`, and restores any protected field the model touched. This keeps A6's
output small (see `design/0001-lean-agent-output-contracts.md`).

## Protected fields & donor-aware exclusion

`PROTECTED_FIELDS` (personal_info, education, languages, countries_of_experience, certifications,
present/proposed_position, …) must never be compressed; `restore_protected_fields`
(`pipeline/precompute_utils.py`) is the safety net. For **GIZ**, `activities_performed` is cleared in
the A6 input (it isn't rendered for GIZ, so compressing it wastes budget) and the original is retained
from the pre-compression copy. WB compresses `activities_performed` normally.

## Contracts & invariants

- LLM call via `call_agent_json` with a `reduce_input` (trims project text on failure).
- `words_after` is always the Python-computed authoritative count, not the LLM's estimate.
- `check_compressor_warnings` (`pipeline/validators.py`) emits `applied_false` /
  `target_not_reached` / `words_after_suspiciously_low` soft-flags, backfilled onto the manifest.
- `other_skills` is a single free-text string (one compressible unit), not a per-item list.

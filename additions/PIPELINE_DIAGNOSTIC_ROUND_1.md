# Pipeline Diagnostic — Round 1 Implementation Record

**Date**: May 2026
**Status**: Complete
**Tests after round**: 168/168 passing

---

## Fixes delivered

### Fix 1 — Upgrade Agent 4 to Sonnet

**Problem**: A4 was using `claude-haiku-4-5-20251001`. Haiku consistently failed
on the generative synthesis task, producing empty `generated_fields[].content`
across all entries. The scaffolding was valid JSON but every `content` field was
an empty string.

**Implementation**: `ANTHROPIC_SYNTHESIS_MODEL = "claude-sonnet-4-20250514"` added
to `pipeline/config.py`. `fields_generator.py` imports and uses this constant. All
other agents (A1–A3, A5, A6) were centralised onto `ANTHROPIC_MODEL` (Haiku) from
the same module as a prerequisite.

---

### Fix 3 — Centralise CEFR mapping at Agent 1 write time

**Problem**: `reading_cefr`, `speaking_cefr`, `writing_cefr` were empty strings in
every artifact. Only `*_raw` fields were populated. The renderer bridged this at
render time via `_resolve_cefr` in `giz.py`, creating a dual-representation
liability across the schema.

**Implementation**: `_populate_cefr_fields(parsed: CVData)` added to
`pipeline/agents/cv_extractor.py`. Called after LLM parse and param injection,
before `cv_data.json` is written. Maps `*_raw → *_cefr` for every language entry
whose structured field is empty (idempotent — never overwrites an existing value).
The renderer's `_resolve_cefr` fallback and Agent 7's CEFR enrichment block remain
as defensive layers but are no-ops for new sessions.

17 tests in `tests/test_cv_extractor_cefr.py`.

**Note**: Fix 3 exposed normalisation gaps in `map_cefr` — tracked as Issue G,
addressed in Fix 7 (Round 2) and Fix M Part 1 (Round 3).

---

### Fix 5a — Hard-block validator after Agent 4

**Problem**: No semantic check existed between A4 and A5. Structurally valid but
semantically empty output (all `content: ""`) passed silently through the full
pipeline.

**Implementation**: `pipeline/validators.py` — new file containing:
- `PipelineValidationError` exception class.
- `validate_fields_generator_output(generated_fields)` — fires before A5 if every
  `generated_fields[].content` is empty. Overrides `fields_generator` manifest
  step to `failed`, calls `set_failed()` with a structured message. A5 and A6
  do not run.

Wired in `orchestrator.run_phase3` between A4 and A5.

20 tests in `tests/test_validators.py`.

**Testing note**: Fix 5a correctly caught generation failures in Runs 3, 5, and 6
of post-implementation testing across three distinct failure modes — token
exhaustion from many large projects (Issue H), weak CV-ToR alignment with sparse
input (Issue K), and token exhaustion from few but extremely large projects in a
World Bank session (Issue L).

---

### Fix 6 — Surface Agent 7 routing decision via the API

**Problem**: A7's internal `_key_qualification_source` routing decision (whether
it edits A4's generated content or A1's raw extraction) was not surfaced in the
API response. The user had no signal that their edits were targeting extracted
rather than generated content.

**Implementation**:
- `_KQ_SOURCE_API_LABEL` dict and `kq_source_label(generated)` helper added to
  `field_editor.py`. Translates internal values to API labels:
  `"ai_generated"` / `"extracted"` / `"absent"`.
- `run()` returns `(applied, skipped, kq_source)`. `kq_source` computed from the
  `mutated` state after `run_field_editor` returns.
- `FieldEditResponse` in `api/models/requests.py` gains
  `kq_source: Literal["ai_generated", "extracted", "absent"]`.
- `orchestrator.run_field_editor_task` updated to return and thread `kq_source`.
- `api/routers/sessions.py` router updated.

11 new tests in `tests/test_field_editor_context.py`. `tests/test_field_editor_skip_reasons.py`
updated — `_base_kwargs` includes `kq_source="ai_generated"`.

---

## Files changed

| File | Change |
|------|--------|
| `pipeline/config.py` | `ANTHROPIC_SYNTHESIS_MODEL = "claude-sonnet-4-20250514"` (A4); `ANTHROPIC_MODEL` centralised for all other agents. |
| `pipeline/validators.py` | **New.** `PipelineValidationError` + `validate_fields_generator_output`. |
| `pipeline/orchestrator.py` | Validator wired between A4 and A5 in `run_phase3`. `run_field_editor_task` updated to return and thread `kq_source`. |
| `pipeline/agents/cv_extractor.py` | `ANTHROPIC_MODEL` from config. `map_cefr` imported. `_populate_cefr_fields` added and called pre-write. |
| `pipeline/agents/tor_summarizer.py` | `ANTHROPIC_MODEL` from config. |
| `pipeline/agents/cv_tor_mapper.py` | `ANTHROPIC_MODEL` from config. |
| `pipeline/agents/fields_generator.py` | `ANTHROPIC_SYNTHESIS_MODEL` from config. A4 now runs on Sonnet. |
| `pipeline/agents/compressor.py` | `ANTHROPIC_MODEL` from config. |
| `pipeline/agents/field_editor.py` | `_KQ_SOURCE_API_LABEL` dict and `kq_source_label(generated)` helper. `run()` returns `(applied, skipped, kq_source)`. |
| `api/models/requests.py` | `FieldEditResponse` gains `kq_source: Literal["ai_generated", "extracted", "absent"]`. |
| `api/routers/sessions.py` | `kq_source` destructured from task and passed into response. |
| `tests/test_validators.py` | **New.** 20 tests. |
| `tests/test_cv_extractor_cefr.py` | **New.** 17 tests. |
| `tests/test_field_editor_context.py` | 11 new tests for `kq_source_label` and `run()` return signature. |
| `tests/test_field_editor_skip_reasons.py` | `_base_kwargs` updated to include `kq_source="ai_generated"`. |

---

## Test results

**168/168 tests passing after Round 1.**

---

## Production validation

Round 1 production validation confirmed A4 on Sonnet generates non-empty
`generated_fields` content. A5 review quality improved significantly — precise,
evidence-grounded findings compared to the shallow output seen with Haiku-generated
content. Fix 5a validator confirmed firing correctly on failure cases.

---

## Markdowns updated

`PIPELINE_CONTEXT.md`, `PROMPT_REVIEW_CONTEXT.md`, `PROMPT_REVIEW_IMPLEMENTATION.md`,
`RUNS_ARTIFACTS_CONTEXT.md`, `API.md`, `FRONTEND_SKIP_REASONS_CONTEXT.md`,
`PIPELINE_DIAGNOSTIC_CONTEXT.md`.

**Additional correction applied in Round 2**: `PROMPT_REVIEW_CONTEXT.md` stated
that `extraction_warnings` is "aspirational and not actively populated by Agent 1."
Run 4 confirmed it is actively populated — Agent 1 correctly flagged a numeric
language scale and reversed date ranges. This statement was removed in Round 2
markdown updates.

---

## Design decisions recorded

**Model naming**: `ANTHROPIC_SYNTHESIS_MODEL` chosen over `FIELDS_GENERATOR_MODEL`
or `ANTHROPIC_MODEL_A4` — encodes the task class not the agent, enabling future
tier expansion.

**Fix 5a validator scope**: All-or-nothing hard block (every entry empty = halt).
Per-key or minimum-count threshold deferred to after Sonnet baseline data collected.

**Fix 5a manifest status on failure**: Override `fields_generator` to `failed`
(not a new `agent_failed` status) — consistent with existing infrastructure,
unambiguous to frontend.

**`kq_source` API labels**: `"ai_generated"` / `"extracted"` / `"absent"` chosen
over internal `"generated_fields"` / `"raw"` / `"none"` — API speaks product
language, not implementation language.

**`kq_source` location**: Added to outer `run()` only, not `run_field_editor` —
27 test assertions on `run_field_editor` preserved, `kq_source` computed from
`mutated` after return.

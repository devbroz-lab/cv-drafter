# Prompt Review Context — CV Reformatter Pipeline

Single reference for the findings, architectural facts, and correction plan
produced during the full prompt review of all seven pipeline agents.
Use this alongside `PIPELINE_CONTEXT.md`, `RENDERER_CONTEXT.md`, and
`RUNS_ARTIFACTS_CONTEXT.md`.

---

## 1. What each agent actually is

All seven agents are **single prompted LLM calls**, not autonomous agents in
the tool-use sense. There is no loop, no tool schema, and no self-directed
decision about what to do next. The term "agent" is used in the older sense
of "a discrete processing unit with a defined role." Each agent:

- Receives a system prompt and a user message assembled from tagged blocks
- Makes one LLM call (with retry logic in the runner)
- Writes a JSON artifact to `runs/{session_id}/`
- Has no memory of previous sessions or previous pipeline runs

The only partial exception is **Agent 7 (Field Editor)**, which is called
once per edit (up to 5 sequential calls), each operating on the already-
patched state from the prior call.

---

## 2. Input assembly — how each agent receives its data

| Agent | System prompt var | User message structure |
|-------|------------------|------------------------|
| A1 CV Extractor | `SYSTEM_PROMPT` | `<cv>...</cv>` raw text + donor tag |
| A2 ToR Summarizer | `SYSTEM_PROMPT` | `<tor>...</tor>` raw text (or no-ToR fallback) |
| A3 CV-ToR Mapper | `SYSTEM_PROMPT` | `<cv_data>`, `<tor_data>`, `<params>` |
| A4 Fields Generator | `SYSTEM_PROMPT_A4` | `<cv_data>`, `<tor_data>`, `<format_profile>`, `<params>` |
| A5 Content Reviewer | `SYSTEM_PROMPT_A5` | `<cv_data>`, `<tor_data>`, `<generation_warnings>`, `<pre_computed>` |
| A6 Compressor | `SYSTEM_PROMPT_A6` | `<cv_data>`, `<tor_data>`, `<compression_params>` |
| A7 Field Editor | `SYSTEM_PROMPT_A7` | Plain sections: `Field path`, `Current value`, `Edit instruction` |

**No-ToR path**: when no ToR is uploaded, Agent 2 receives empty text.
This is enforced at the backend/frontend layer — no prompt instruction needed.
Agents 3 and 4 receive an essentially empty `DistilledToR`; all list fields
are `[]`, all strings are `""`. Downstream agents handle this implicitly via
their "if not found, leave as []" rules.

---

## 3. Schema facts relevant to prompts

### CVData — key points for prompt writers

- **`generated_fields: list[GeneratedField]`** — the canonical output of
  Agent 4. Each entry has `field_key`, `content`, `source`. Renderers read
  this, not the raw extracted equivalents, for format-specific content.
- **`key_qualifications: list[str]`** — extracted from the CV by Agent 1.
  Agent 4 may leave this unchanged (GIZ) or generate into `generated_fields`
  with `field_key="key_qualifications"`. Renderer prefers `generated_fields`.
- **`detailed_tasks: list[DetailedTask]`** — exists on the model but is
  **not used by the rendering path**. WB tasks are written as `GeneratedField`
  items with `field_key="detailed_tasks"` into `generated_fields`. This is
  intentional (uniformity). `DetailedTask` is legacy/unused in the active pipeline.
- **`employment_record: list[EmploymentRecord]`** — WB only. GIZ leaves as `[]`.
- **`extraction_warnings: list[str]`** — actively populated by Agent 1
  when it detects non-standard proficiency scales, reversed date ranges, or
  other extraction quality concerns. Confirmed via live session runs (Run 4
  flagged a numeric language scale; Run 4 flagged reversed date ranges).
  Agent 5 and Agent 7 may read this field for context; treat it as advisory.
- **`activities_performed`** on `RelevantProject` — intentionally left empty
  in GIZ extraction. Agent 5 must not require it as evidence. Also left as `""`
  in employment-only fallback mode (Fix CC): descriptive employment text is routed
  to `main_project_features` instead, so the renderer's project-overview paragraph
  is populated first. As of Round 7 (Fix LL), Agent 6 also skips this field for
  GIZ runs entirely — it is not rendered in any GIZ table cell, so compressing it
  wastes word budget. WB runs compress it normally.

### DistilledToR — key points for prompt writers

- **`geography: str`** — flat string field. **Agent 2 now populates it** as a
  short human-readable geographic scope string (e.g. "South Africa",
  "Sub-Saharan Africa"). It is a display-only field. Agent 3 uses
  `country_experience_required` (not `geography`) for scoring — see P6.
- **`country_experience_required: list[str]`** — the actual populated field
  for geographic requirements. Use this in all agents.
- **`geographic_requirement`, `applied_role_tier`, `task_clusters`,
  `structured_competencies`** — exist on the model as structured enrichments.
  Not deterministically populated by post-processing in Agent 2 currently.
  May be emitted by the LLM but are not guaranteed. Do not treat as a
  required contract in downstream agent prompts.
- **`required_competencies` / `preferred_competencies`** — flat `list[str]`.
  The structured mirror (`structured_competencies`) is not reliably populated.
  Use the flat lists.

### FORMAT_PROFILES — active values

| Format | `generative_field_keys` | `language_scale` | `page_limit_default` |
|--------|------------------------|-----------------|----------------------|
| `giz` | `["key_qualifications"]` | `"cefr"` | 4 |
| `world_bank` | `["detailed_tasks"]` | `"freetext"` | 4 |

Both formats: `default_target_words=0`, `default_compression_ratio=0.80`.
However, the active compression path uses `get_compression_params()` from
`templates/registry.py`, which computes `target_words = page_limit × words_per_page`.
This means **`target_words > 0` is normal in production**. The ratio fallback
applies only when `target_words` resolves to 0.

---

## 4. Python post-processing — what agents do NOT need to handle

These things are handled deterministically in Python after the LLM responds.
Agent prompts should not attempt to replicate them.

### After Agent 5 (Content Reviewer)

| Function | What it does |
|----------|-------------|
| `_enforce_passed_field` | Forces `passed=false` if `high_severity` is non-empty. Agent 5's own value is overridden if wrong. |
| `_inject_experience_gap_finding` | If candidate is `team_lead` tier and has an energy-sector experience gap ≥ threshold, injects a `high_severity` finding regardless of LLM output. |
| `_filter_word_count_pedantry` | Removes low_severity word-count flags within `WORD_COUNT_TOLERANCE_PCT` of the limit. |

Agent 5 **does** need to know about the experience gap logic to avoid
producing redundant or contradictory findings alongside the injected one.
See P3 in the correction plan.

### After Agent 6 (Compressor)

Word counts (`words_before`, `words_after`) reported by the LLM are
approximations. Python should compute authoritative counts from the actual
JSON output if these values are displayed in the UI.

### reviewer_blocked status

`content_reviewer` can set manifest step status to `"blocked"`, and
`manifest.reviewer_blocked` can be `true`. However, the orchestrator
(`run_phase3`) does **not** transition the DB coarse status to
`reviewer_blocked` for new sessions — it logs a warning and continues to
the compressor. The DB status `reviewer_blocked` is effectively dead for
normal sessions. `passed: false` is surfaced via `GET /review` instead.

---

## 5. Implementation status

| Problem | Status | File(s) changed |
|---------|--------|-----------------|
| P2 (LLM arithmetic) — A4 duration/year | **Implemented** | `precompute_utils.py`, `fields_generator.py` |
| P2 (LLM arithmetic) — A6 word counts | **Implemented** | `precompute_utils.py`, `compressor.py` |
| P2 (LLM arithmetic) — A3 relevance scoring | **Deferred (stub)** | `cv_tor_mapper.py` — see `RELEVANCE_SCORING_DESIGN.md` |
| P3 — Agent 5 pre-computed context undocumented | **Implemented** | `content_reviewer.py` (SYSTEM_PROMPT_A5) |
| P4 — Agent 5 auto-fix note | **Implemented** | `content_reviewer.py` (SYSTEM_PROMPT_A5) |
| P5 — Agent 7 missing context | **Implemented** | `field_editor.py`, `orchestrator.py` |
| P6 — geography never populated (Option B + A) | **Implemented** | `tor_summarizer.py` (A), `cv_tor_mapper.py` (B) |
| P11 — Typo rule risks proper nouns (A1) | **Implemented** | `cv_extractor.py` |
| P12 — present_position fallback ambiguous (A1) | **Implemented** | `cv_extractor.py` |
| P13 — min_projects_to_keep no default (A3) | **Implemented** | `cv_tor_mapper.py` |
| P14 — Minimum bullet count conflicts (A4) | **Implemented** | `fields_generator.py` |
| P15 — Duration/year calculation in LLM (A4) | **Implemented** | `precompute_utils.py`, `fields_generator.py` |
| P16 — Word counting unreliable (A6) | **Implemented** | `precompute_utils.py`, `compressor.py` |
| P17 — "Character for character" unenforceable (A6) | **Implemented** | `compressor.py` (prompt + post-compute restore) |
| P18 — No fallback when target unreachable (A6) | **Implemented** | `compressor.py`, `models.py` (CompressionResult) |
| P19 — generation_warnings passthrough missing (A6) | **Implemented** | `compressor.py` |
| Agent 4 model upgrade (Haiku → Sonnet) | **Implemented** | `pipeline/config.py` (`ANTHROPIC_SYNTHESIS_MODEL`), `fields_generator.py` |
| Model centralisation (A1–A3, A5, A6 import from config) | **Implemented** | `pipeline/config.py`, `cv_extractor.py`, `tor_summarizer.py`, `cv_tor_mapper.py`, `compressor.py` |
| Hard-block validator after A4 (empty `generated_fields[].content`) | **Implemented** | `pipeline/validators.py` (new), `pipeline/orchestrator.py` |
| CEFR centralisation at A1 write time | **Implemented** | `pipeline/agents/cv_extractor.py` (`_populate_cefr_fields`) |
| Agent 7 `kq_source` surfaced via API | **Implemented** | `field_editor.py` (`kq_source_label`), `orchestrator.py`, `api/models/requests.py`, `api/routers/sessions.py` |
| Fix 9 — `FieldShortened.subfield` optional | **Implemented** | `models.py` |
| Fix 7 — `map_cefr` parenthetical + numeric normalisation | **Implemented** | `pipeline/utils/cefr.py` |
| Fix J — Python enforcement of A3 threshold | **Implemented** | `pipeline/agents/cv_tor_mapper.py` (`_enforce_threshold_and_cap`) |
| Fix 8 Part 1 — Hard project cap (`MAX_PROJECTS_TO_KEEP = 6`) | **Implemented** | `pipeline/agents/cv_tor_mapper.py` |
| Fix 8 Part 3 — Per-project text cap before A4 | **Implemented** | `pipeline/agents/fields_generator.py` (`_truncate_project_text_for_a4`) |
| Fix 8 Part 2 — A4 prompt priority + minimum output guarantee | **Implemented** | `pipeline/agents/fields_generator.py` (`SYSTEM_PROMPT_A4`) |
| Fix M Part 1 — Numeric 1–5 CEFR scale mapping | **Implemented** | `pipeline/utils/cefr.py` (`NUMERIC_SCALE_TO_CEFR`, rewritten `map_cefr`) |
| Fix M Part 2 — A4 truncation-text restoration before write | **Implemented** | `pipeline/agents/fields_generator.py` (`_restore_truncated_project_text`, `cv_data_full` preservation) |
| Fix N — Project floor/threshold/cap recalibration | **Implemented** | `pipeline/agents/cv_tor_mapper.py` (constants + `_compute_threshold` + dynamic floor + `SYSTEM_PROMPT_A3` mirror) |
| Fix O — Numeric CEFR scale direction detection + 1_best default | **Implemented** | `pipeline/utils/cefr.py` (`NUMERIC_SCALE_TO_CEFR_INVERTED`, `map_numeric_scale_inverted`), `models.py` (`language_scale_direction`), `cv_extractor.py` (`_apply_cefr_with_direction`, `_populate_cefr_fields`, prompt) |
| Fix P — A4 prompt: prefer candidate's own KQ bullets when bullet-style | **Implemented** | `pipeline/agents/fields_generator.py` (`SYSTEM_PROMPT_A4` source-preference subsection) |
| Fix Q — A1 prompt: label-driven `other_skills` routing | **Implemented** | `pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1` routing section) |
| Fix R — `references` and `certification_declaration` schema + extraction + context | **Implemented (rendering deferred)** | `models.py` (`Reference`, new CVData fields), `cv_extractor.py` (prompt), `templates/giz.py`, `templates/wb.py` |
| Fix U — A1 unfilled placeholder detection | **Implemented** | `pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1` placeholder detection section) |
| Fix 2 — All agents to Sonnet | **Implemented** | `pipeline/config.py` (`ANTHROPIC_MODEL` → Sonnet) |
| Fix 4b — A2 `scoring_keywords` extraction | **Implemented** | `models.py` (`ScoringKeywords`, `DistilledToR.scoring_keywords`), `pipeline/agents/tor_summarizer.py` (`SYSTEM_PROMPT_A2`) |
| Fix 4 — Python relevance scoring for Agent 3 + duration upstream | **Implemented** | `pipeline/precompute_utils.py` (new scoring helpers), `pipeline/agents/cv_tor_mapper.py` (real implementation + upstream duration + A3 prompt), `pipeline/agents/fields_generator.py` (pre-compute call removed) |
| Fix 5b — Soft-flag manifest warnings | **Implemented** | `pipeline/manifest.py` (`append_warning`), `pipeline/validators.py` (3 check functions), `pipeline/orchestrator.py` (wired in phase 3) |
| Fix Z — A6 pre-processing word cap | **Implemented** | `pipeline/agents/compressor.py` (`A6_INPUT_PROJECT_WORD_CAP`, `_truncate_project_text_for_a6`, `append_warning` calls for truncation events) |
| Fix AA — A4 guarantee extended to `detailed_tasks` | **Implemented** | `pipeline/agents/fields_generator.py` (`SYSTEM_PROMPT_A4` minimum output guarantee — explicit WB `detailed_tasks` + geographic exemption rule) |
| Fix V — A1 merged-cell project name extraction | **Implemented** | `pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1` `### Merged-cell and two-column project tables` section) |
| Fix W — A1 date ordering validation + auto-correct | **Implemented** | `pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1` `### Date ordering validation` section — all four date-field types) |
| Fix Y — A2 `scoring_keywords` reorder + soft-flag | **Implemented** | `pipeline/agents/tor_summarizer.py` (section moved after `position_title`; non-empty guarantee), `pipeline/validators.py` (`check_tor_summarizer_warnings`), `pipeline/orchestrator.py` (wired in `run_phase1`) |
| Fix CC — A1 employment-only fallback: `description → main_project_features` | **Implemented** | `pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1` `### Employment-only fallback` section: `description → main_project_features`, `employer → project_name + company`, `activities_performed` / `client` / `donor` left as `""`; `_apply_employment_fallback` Python safety net with matching routing; short-description warning references `main_project_features`) |
| Fix DD — A1 prompt: "References" section citations → `publications[]` | **Implemented** | `pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1` — added explicit routing rule: academic citations → `publications[]`; contact references → `references[]`) |
| Fix FF-A — A1 prompt: formal credentials dual-route to `certifications[]` + `membership_professional_bodies` | **Implemented** | `pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1` — formal engineering/professional credentials route to both `certifications[]` and `membership_professional_bodies`) |
| Fix FF-B — A4 prompt: add `certifications[]` as KQ evidence source | **Implemented** | `pipeline/agents/fields_generator.py` (`SYSTEM_PROMPT_A4` — `certifications[]` added to evidence sources list for generating KQ bullets) |
| Fix JJ — Remove A4 truncation-and-restore (redundant with current model) | **Implemented** | `pipeline/agents/fields_generator.py` — `_truncate_project_text_for_a4`, `_restore_truncated_project_text`, `A4_INPUT_PROJECT_WORD_CAP`, and `cv_data_full` preservation removed. A4 receives full untruncated project text. |
| Fix KK — Remove A6 truncation entirely (silent data loss) | **Implemented** | `pipeline/agents/compressor.py` — `_truncate_project_text_for_a6`, `A6_INPUT_PROJECT_WORD_CAP`, and all `input_field_truncated` manifest warning emissions removed. |
| Fix LL — A6 donor-aware compression: exclude `activities_performed` for GIZ | **Implemented** | `pipeline/agents/compressor.py` — for GIZ runs, `activities_performed` cleared in `cv_data_for_a6` before A6 LLM call and restored after. `SYSTEM_PROMPT_A6` updated with donor-aware field exclusion note. |
| Fix EE — Post-cap chronological sort of `relevant_projects` + `countries_of_experience` | **Implemented** | `pipeline/agents/cv_tor_mapper.py` — `_sort_by_date_desc` applied after `_enforce_threshold_and_cap`; uses `_parse_date` from `precompute_utils.py`. |
| Fix II-B — A7 `RENDERER_FIELD_MAP` + redirect/skip non-rendered fields | **Implemented** | `pipeline/agents/field_editor.py` — `RENDERER_FIELD_MAP`, `_RENDERER_REDIRECT_MAP`, `_check_renderer_field()` added; `SYSTEM_PROMPT_A7` updated with donor-aware field path guidance. |
| Fix MM — API warning endpoint | **Implemented** | `api/models/requests.py` (`WarningEntry`, `WarningsResponse` models); `api/routers/sessions.py` (`GET /sessions/{id}/warnings` endpoint aggregating warnings from all four run-directory artifacts) |

---

## 5a. Correction plan — problems and fixes (original, preserved for reference)

### P2 — LLM arithmetic (Agents 3, 4, 6)

**Problem**: Three agents are asked to count words, calculate date durations,
compute weighted relevance scores, and hit numeric word-count targets. LLMs
cannot do this reliably or consistently.

**Fix approach**:
- **Agent 3**: Move relevance scoring to a Python pre-compute step. Pass
  per-project scores into the prompt as `<pre_computed>` so the LLM selects
  and explains rather than calculates.
- **Agent 4**: Move `duration` and `year` derivation to Python pre-processing.
  Pass pre-filled values to Agent 4; instruct it to copy them, not compute them.
- **Agent 6**: Move `words_before` calculation to Python. Pass total word count
  and per-field word counts into `<compression_params>`. The LLM reports
  `words_after` as an estimate; Python computes the authoritative value
  post-response.

### P3 — Agent 5 has no instructions for `<pre_computed>` fields

**Problem**: Agent 5 receives `tier`, `required_experience_years`,
`documented_energy_years`, `experience_gap_years`, and `geographic_alternative`
in `<pre_computed>` but the prompt never tells it what to do with them.
Python post-processing backstops the experience gap check — but the LLM
may produce redundant or contradictory findings alongside the injected one.

**Fix approach**: Add a dedicated `## Pre-computed context` section to the
Agent 5 prompt explaining each field and how to use it:
- If `experience_gap_years > 0` and `tier == "team_lead"`: acknowledge the
  gap exists; do not independently calculate or re-flag it (Python will inject
  the finding). Instead, use it to calibrate how strictly to apply geographic
  and competency checks.
- Use `geographic_alternative` to inform the geographic gap check — if an
  alternative pathway exists, downgrade from high to low severity.
- Use `tier` to calibrate leadership language expectations.

### P4 — Agent 5 reviews its own auto-fixes

**Problem**: Low-severity fixes are applied inline to `data` before the
review block is finalized. The agent cannot catch errors it introduced itself.

**Fix approach**: Add a note in the prompt that auto-fixes are applied once,
are not re-reviewed, and should therefore be conservative. Instruct the agent
to prefer the minimal rewrite that resolves the issue — never introduce new
claims, expand scope, or change meaning beyond what is necessary to fix the
flagged problem.

### P5 — Agent 7 missing context

**Problem**: The field editor sees only the current field value and an
instruction. It has no knowledge of word limits, donor format conventions,
field type (string vs list item), or the surrounding CV.

**Fix approach**: Extend the Agent 7 user message to include:
- `Field key` — the logical field being edited (e.g. `key_qualifications`)
- `Donor format` — `giz` or `world_bank`
- `Word limit` — the applicable limit for this field type (25 for GIZ bullets,
  30 for WB tasks), passed from the orchestrator
- `CV context snippet` — the `proposed_position` and top 2–3 project names,
  to give the editor minimal grounding without overwhelming the prompt

### P6 — `geography` field never populated by Agent 2

**Problem**: `DistilledToR.geography` is a flat string field that Agent 2
never populates. Agent 3 references `DistilledToR.geography` in its geography
scoring dimension but receives an empty string every time.

**Fix approach** (two options, pick one):
- **Option A**: Add `geography` to Agent 2's extraction rules — populate it as
  a single short string summarising the primary geographic scope
  (e.g. "South Africa", "Sub-Saharan Africa"). Simplest fix.
- **Option B**: Update Agent 3's scoring rules to use `country_experience_required`
  (which IS populated) instead of `geography`. More accurate since it preserves
  the list structure.
- **Recommended**: Option B, because `country_experience_required` is richer
  and already correct. Also add Option A as a supplementary field for human-
  readable display.

### P11 — Typo rule risks proper nouns (Agent 1)

**Problem**: "Fix obvious typos only where unambiguous" is subjective and
risks corrupting proper nouns, institution names, and country names.

**Fix approach**: Narrow the rule explicitly:
- Never apply typo correction to proper nouns, names, institutions, companies,
  countries, or acronyms.
- Only apply to common words where the correction is unambiguous
  (e.g. "teh" → "the", "recieve" → "receive").
- If uncertain, leave as found.

### P12 — `present_position` fallback ambiguous (Agent 1)

**Problem**: "Most recent entry in `relevant_projects`" is undefined when
multiple projects have `date_to: "Present"`.

**Fix approach**: Define "most recent" explicitly:
1. Projects with `date_to: "Present"` rank above all others.
2. Among multiple "Present" entries, use the one with the latest `date_from`.
3. Among dated entries, use the one with the latest `date_to`.
4. If still tied, use the first entry in document order.

### P13 — `min_projects_to_keep` has no default (Agent 3)

**Problem**: The prompt references this value from `<params>` with no
fallback if it's absent.

**Fix approach**: Add to the prompt: "If `min_projects_to_keep` is not
present in params, default to 3."

### P14 — Minimum bullet count conflicts with sparse ToRs (Agent 4)

**Problem**: Minimum 3 bullets is forced even when the ToR contains fewer
than 3 distinct competency clusters, causing padding.

**Fix approach**: Change the rule to: "Generate one bullet per major
competency cluster the ToR requires. Aim for 3–6 bullets. If the ToR
clearly contains fewer than 3 distinct clusters, generate one bullet per
cluster — do not pad. Minimum is 1 strong bullet, not 3."

### P15 — Duration/year calculation in LLM (Agent 4)

**Problem**: Agent 4 calculates `duration` and `year` from date strings.
LLMs are unreliable at date arithmetic.

**Fix approach**: Move both calculations to Python pre-processing before
Agent 4 runs. Pass pre-filled `duration` and `year` values per project in
the `<cv_data>` block. Update Agent 4's prompt: "The `duration` and `year`
fields have been pre-computed by the pipeline. Copy them exactly as received —
do not recalculate."

### P16 — Word counting unreliable (Agent 6)

**Problem**: Agent 6 is asked to count words across all compressible fields,
hit a numeric target, and report authoritative before/after counts. LLMs
cannot do this reliably.

**Fix approach** (revised given Q5 answer — `target_words > 0` is normal):
- Compute `words_before` and per-field word counts in Python before calling
  Agent 6. Pass these in `<compression_params>`.
- Instruct Agent 6 to use the provided `words_before` in its output block
  rather than counting itself.
- Accept that `words_after` is an LLM estimate. Python computes the
  authoritative post-compression count from the actual output JSON.
- Add to prompt: "You are provided with `words_before` and `words_per_field`.
  Use these values directly in your compression block. Do not recount."

### P17 — "Character for character" unenforceable (Agent 6)

**Problem**: The prompt claims protected fields will be returned "exactly,
character for character." An LLM cannot guarantee this.

**Fix approach**: Remove the "character for character" language. Replace with:
"Protected fields must not be compressed or paraphrased. Return them as
received. Python post-processing will restore any protected fields that were
accidentally altered — but do not alter them intentionally."

### P18 — No fallback when compression target unreachable (Agent 6)

**Problem**: If the content cannot be reduced to `target_words` without
violating the rules, the agent has no instruction. It will silently get as
close as it can.

**Fix approach**: Add: "If you cannot reach `target_words` without violating
these rules (removing a GeneratedField item, changing a proper noun, etc.),
compress as much as possible within the rules and set a `target_not_reached`
field to `true` in the compression block. Do not violate the rules to hit
the number."

### P19 — `generation_warnings` passthrough undocumented (Agent 6)

**Problem**: Agent 4 produces `generation_warnings`. Agent 5 receives and
uses them. Agent 6's output shape has no `generation_warnings` field and
the prompt says nothing about passthrough.

**Fix approach**: Add `generation_warnings` to Agent 6's output shape:
```json
{
  "data": { ... },
  "compression": { ... },
  "generation_warnings": []
}
```
Add to prompt: "The `generation_warnings` list from Agent 4 is passed through
unchanged. Copy it into your output exactly as received — do not modify,
add to, or remove from it."

---

## 6. Items documented but not corrected

| Item | Reason not corrected |
|------|---------------------|
| `DetailedTask` model unused | Intentional — WB tasks use `GeneratedField` for pipeline uniformity. Document in schema comments only. |
| Structured `DistilledToR` fields not wired | Schema-level aspirations, not guaranteed by post-processing. No prompt references until deterministically populated. |
| `extraction_warnings` aspirational | ~~Not actively populated by Agent 1~~ — **corrected in Round 2**: Run 4 confirmed it is actively populated. This row is superseded by the updated §3 entry above. |
| `reviewer_blocked` DB status | Dead for normal sessions. Docs should be updated to reflect manifest-only usage. |

---

## 7. Quick reference — which Python step owns what

| Computation | Owner | Implemented in |
|-------------|-------|----------------|
| `duration` per project | Python pre-processing before A4 | `precompute_utils.compute_project_duration` → `fields_generator._precompute_project_dates` |
| `year` per project | Python pre-processing before A4 | `precompute_utils.compute_project_year` → `fields_generator._precompute_project_dates` |
| `words_before` and per-field counts | Python pre-processing before A6 | `precompute_utils.count_words_per_field` → `compressor.run` |
| `words_after` authoritative count | Python post-processing after A6 | `precompute_utils.count_compressible_words_total` in `compressor.run` |
| Protected field restoration | Python post-processing after A6 | `precompute_utils.restore_protected_fields` in `compressor.run` |
| `passed` enforcement | Python post-processing after A5 | `content_reviewer._enforce_passed_field` |
| Experience gap injection | Python post-processing after A5 | `content_reviewer._inject_experience_gap_finding` |
| Word count tolerance filtering | Python post-processing after A5 | `content_reviewer._filter_word_count_pedantry` |
| Relevance scoring (deferred) | Python pre-processing before A3 | `cv_tor_mapper._precompute_relevance_scores` stub — see `RELEVANCE_SCORING_DESIGN.md` |
| Threshold enforcement + project cap | Python post-processing after A3 (in `run()`) | `cv_tor_mapper._enforce_threshold_and_cap` |
| Per-project text cap for A4 input | **Removed (Fix JJ, Round 7)** — A4 receives full text | `fields_generator._truncate_project_text_for_a4` deleted |
| CEFR field population | Python post-processing after A1 LLM | `cv_extractor._populate_cefr_fields` using `pipeline.utils.cefr.map_cefr` |
| A4 input text restoration | **Removed (Fix JJ, Round 7)** — no truncation, no restore step needed | `fields_generator._restore_truncated_project_text` deleted |
| CEFR scale direction mapping | Python post-processing after A1 LLM (in `cv_extractor._populate_cefr_fields`) | `_apply_cefr_with_direction(raw, direction)` — uses `map_cefr` (1_best default) or `map_numeric_scale_inverted` (1_worst) based on `CVData.language_scale_direction` |
| A3 threshold + cap enforcement | Python post-processing after A3 LLM (in `cv_tor_mapper.run`) | `_enforce_threshold_and_cap` — thresholds `0.30/0.40/0.50`; floor `min(MIN, total)`; current constants: `MIN=5`, `MAX=15` |
| A3 Python relevance pre-compute | Python pre-processing before A3 LLM (in `cv_tor_mapper.run`) | `_precompute_relevance_scores` — keyword overlap (35%) + geography (15%) = 50% Python-computed; LLM adjusts ±0.10 for semantic dimensions |
| A2 scoring keywords | LLM extraction in A2 (`tor_summarizer.run`) | `SYSTEM_PROMPT_A2` `### scoring_keywords` (reordered to after `position_title`, Fix Y) — three lists (`role_implied`, `scope_implied`, `explicit`) with non-empty guarantee |
| A6 pre-processing truncation | **Removed (Fix KK, Round 7)** — A6 receives full text | `compressor._truncate_project_text_for_a6` deleted; no `input_field_truncated` warnings emitted |
| A6 donor-aware field exclusion | Python pre-processing before A6 LLM (Fix LL, Round 7) | `compressor.run` — for GIZ runs, `activities_performed` cleared in `cv_data_for_a6` before A6 call, restored after (field not rendered in GIZ output; WB unaffected) |
| `relevant_projects` + `countries_of_experience` chronological sort | Python post-processing after A3 LLM (Fix EE, Round 7) | `cv_tor_mapper._sort_by_date_desc` — descending `date_from`; applied after `_enforce_threshold_and_cap`; uses `_parse_date` from `precompute_utils.py` |
| A1 extraction normalisation | LLM prompt instructions in A1 | `SYSTEM_PROMPT_A1` — unfilled placeholder detection (Fix U); merged-cell project name extraction (Fix V); date ordering validation + auto-correct (Fix W); employment-only fallback routing (Fix CC). |
| Employment-only fallback (Python safety net) | Python post-processing after A1 LLM (in `cv_extractor.run`) | `cv_extractor._apply_employment_fallback` — when `relevant_projects` is empty and `employment_record` has entries, maps each employment entry: `description → main_project_features`, `employer → project_name + company`, `activities_performed / client / donor = ""`. Idempotent — skips when projects already present. |
| Manifest soft-flag warnings | Post-processing after A2, A4, A5, A6 | `check_tor_summarizer_warnings` (after A2), `check_fields_generator_warnings`, `check_content_reviewer_warnings`, `check_compressor_warnings` — results appended via `manifest.append_warning` |

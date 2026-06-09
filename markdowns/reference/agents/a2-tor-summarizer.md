---
title: A2 — ToR Summarizer
type: reference
status: current
owner: backend
last_verified: 2026-06-08
code_refs:
  - pipeline/agents/tor_summarizer.py
  - pipeline/validators.py
  - pipeline/utils/llm.py
  - models.py
related:
  - reference/data-model.md
  - reference/agents/a3-cv-tor-mapper.md
---

# A2 — ToR Summarizer

Reads the tagged ToR text and produces one or more `DistilledToR` "pools" (one per distinct expert
role the ToR describes). Runs in parallel with A1 during Phase 1.

- **Model:** Sonnet (`ANTHROPIC_MODEL`).
- **Input:** `<tor>` tagged text, or a no-ToR fallback instruction when none was uploaded.
- **Output:** `tor_data.json` → `{approved, approved_at, pools: [DistilledToR, …], selected_pool_index: 0}`.
- **Manifest step:** `tor_summarizer`.

## What the prompt does (highlights — see `SYSTEM_PROMPT_A2`)

- **Pool detection.** Emit one `DistilledToR` per distinct role; shared fields (languages, geography)
  are duplicated into each pool.
- **`scoring_keywords`** — three lists that feed A3's Python relevance scorer:
  `explicit` (stated requirements: geography, years, sectors), `scope_implied` (themes from the
  scope/background), `role_implied` (technical vocabulary inferred from the position title). At least
  one list must be non-empty for any non-empty ToR.
- **`country_experience_required`** is the canonical geographic requirement (A3 scores on it, not the
  human-readable `geography` string).
- Extracts `key_tasks`, `required`/`preferred_competencies`, `language_requirements`,
  `page_limit_stated`.

## Output handling (`tor_summarizer.run`)

Parses `{ "pools": [...] }`, validates each element as `DistilledToR`, writes the envelope with
`selected_pool_index: 0`. The UI prunes to the chosen pool at checkpoint 1
(`POST /tor/select-pool`); downstream agents resolve the ToR via `resolve_tor_for_agents`
(`pipeline/utils/_helpers.py`).

## No-ToR path

When no ToR is uploaded, A2 receives empty text and returns a single minimal `DistilledToR` (all
fields at defaults). Downstream agents handle empty requirements implicitly.

## Contracts & invariants

- Goes through `call_agent_json` with **no `reduce_input`** (its output — the pools array — is small
  and bounded; its input is raw text it must summarise faithfully).
- `check_tor_summarizer_warnings` (`pipeline/validators.py`) emits `scoring_keywords_empty` /
  `position_title_empty` soft-flags, backfilled onto the manifest after Phase 1.

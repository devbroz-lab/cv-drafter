# Deferred Design — P2-A3: Python Relevance Scoring for Agent 3

Status: **DEFERRED** — stub in place, implementation pending.
See `pipeline/agents/cv_tor_mapper.py:_precompute_relevance_scores`.

---

## Problem statement

The current Agent 3 (CV-ToR Mapper) asks the LLM to score each project across
four weighted dimensions (sector keywords 35%, key tasks 30%, competencies 20%,
geography 15%).  LLMs are inconsistent at this arithmetic.  The goal is to move
the numeric scoring into Python so the LLM's role becomes selection and
explanation rather than calculation.

---

## Proposed interface

`_precompute_relevance_scores(cv_data: dict, tor_data: dict) -> dict | None`

Returns a dict injected into `<pre_computed>` before the LLM call:

```json
{
  "project_scores": [
    {
      "project_name": "Grid Rehabilitation Kano State",
      "keyword_overlap_score": 0.72,
      "keyword_matches": ["grid", "SCADA", "transmission"],
      "country_overlap": ["Nigeria"],
      "duration_years": 2.5,
      "composite_score": 0.65
    },
    ...
  ],
  "scoring_note": "Scores computed by Python keyword-overlap before calling LLM."
}
```

The prompt update instructs the LLM:
- Use `composite_score` as the starting relevance_score for each project.
- Adjust ±0.10 based on semantic task/competency overlap not captured by keyword matching.
- Report your adjusted score and reasoning in `project_scores`.

---

## Scoring algorithm design

### 1. Sector keyword match (35% weight)

```python
def _keyword_score(project: dict, sector_keywords: list[str]) -> float:
    text = " ".join([
        project.get("main_project_features", ""),
        project.get("activities_performed", ""),
        project.get("positions_held", ""),
        project.get("project_name", ""),
    ]).lower()
    if not sector_keywords:
        return 0.0
    hits = sum(1 for kw in sector_keywords if kw.lower() in text)
    return min(1.0, hits / len(sector_keywords))
```

### 2. Key tasks match (30% weight) — DEFERRED to LLM

Semantic matching is hard to do reliably in Python without an embedding model.
Leave this dimension for the LLM to assess — instruct it to adjust the
composite score based on task alignment.

When an embedding API becomes available, implement:
```python
def _task_score(project: dict, key_tasks: list[str]) -> float:
    # cosine similarity between project text embedding and task embeddings
    ...
```

### 3. Competencies match (20% weight) — DEFERRED to LLM

Same reason as tasks — requires semantic matching.

### 4. Geography match (15% weight)

```python
def _geography_score(project: dict, country_experience_required: list[str]) -> float:
    if not country_experience_required:
        return 0.0
    project_location = (project.get("location", "") + " " + project.get("country", "")).lower()
    required_lower = [c.lower() for c in country_experience_required]
    for req in required_lower:
        if req in project_location or project_location in req:
            return 1.0   # exact match
        # region overlap heuristic — e.g. "Africa" in both
        req_parts = req.split()
        loc_parts = project_location.split()
        if any(p in loc_parts for p in req_parts if len(p) > 4):
            return 0.5   # partial / regional match
    return 0.0
```

### Composite (Python-computable portion)

```python
composite = (
    _keyword_score(project, sector_keywords) * 0.35
    + _geography_score(project, country_experience_required) * 0.15
)
# LLM adds the remaining 0.55 weight (tasks 0.30 + competencies 0.25)
# by adjusting composite within ±0.10
```

---

## Prompt update (when implemented)

Add to `SYSTEM_PROMPT_A3` after "## Scoring rules":

```
## Pre-computed scores
A `<pre_computed>` block is provided containing Python-computed keyword and
geography scores for each project.  These are partial scores covering 50% of
the total weighting.

Use them as follows:
- Start from `composite_score` for each project.
- Adjust by up to ±0.10 based on your semantic assessment of task and
  competency alignment (the remaining 50% weight).
- Report your final adjusted `relevance_score` and the `keyword_matches`
  and `country_overlap` lists in your output.
- Do NOT discard or ignore the pre-computed scores — use them as a baseline.
```

---

## Dependencies / blockers

1. No embedding API is currently wired into the pipeline — the task/competency
   semantic matching requires one, or a simpler bag-of-words approach.
2. The prompt update must be staged: add the `<pre_computed>` block first with
   a note it is advisory, then make it authoritative once calibrated.
3. Regression testing required: run a batch of existing sessions with and
   without pre-computed scores to verify project selection quality is maintained.

---

## Files to modify when implementing

| File | Change |
|---|---|
| `pipeline/agents/cv_tor_mapper.py` | Replace `_precompute_relevance_scores` stub with real implementation |
| `pipeline/agents/cv_tor_mapper.py` | Update `SYSTEM_PROMPT_A3` to add pre-computed score usage instructions |
| `pipeline/precompute_utils.py` | Add `keyword_overlap_score`, `geography_score` helpers |
| `tests/test_precompute_utils.py` | Add tests for new scoring helpers |
| `tests/test_cv_tor_mapper.py` | Verify pre-computed block is sent and scores are used |

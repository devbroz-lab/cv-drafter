# Deferred Design — P2-A3: Python Relevance Scoring for Agent 3

Status: **IMPLEMENTED Round 5** — `_precompute_relevance_scores` fully implemented.
See `pipeline/agents/cv_tor_mapper.py` and `pipeline/precompute_utils.py`.

**Round 4 addition**: R5-A extends this design to include keyword extraction
at Agent 2 (ToR Summarizer). A2 will emit a `scoring_keywords` block into
`tor_data.json` which feeds directly into the Python keyword overlap scorer
below. R5-A and R5-B must be implemented in the same round. R5-C (all
agents to Sonnet) must also land in the same round — A2's role-implied keyword
inference requires Sonnet-quality reasoning.

---

## Problem statement

The current Agent 3 (CV-ToR Mapper) asks the LLM to score each project across
four weighted dimensions (sector keywords 35%, key tasks 30%, competencies 20%,
geography 15%). LLMs are inconsistent at this arithmetic. The goal is to move
the numeric scoring into Python so the LLM's role becomes selection and
explanation rather than calculation.

Additionally, the keyword set currently available to A3 is derived from whatever
keywords appear in the ToR body — which may not fully represent the position's
requirements. A role like "Energy Sector Regulatory Expert" implies a set of
technical terms that may not be spelled out in the tasks list. R5-A addresses
this by having A2 extract and infer a richer keyword set before A3 runs.

---

## R5-A — A2 keyword extraction (new, Round 5)

### What A2 will emit

A2's output (`tor_data.json`) will gain a `scoring_keywords` block:

```json
"scoring_keywords": {
  "role_implied": [
    "regulatory framework", "energy policy", "tariff design",
    "grid codes", "market rules", "licensing"
  ],
  "scope_implied": [
    "renewable energy", "grid integration", "distribution sector",
    "prosumers", "energy storage"
  ],
  "explicit": [
    "South Africa", "electricity sector", "7 years experience"
  ]
}
```

**Three keyword sets**:
- `role_implied` — keywords inferred from the position title and pool name that
  a qualified candidate would be expected to demonstrate, even if not listed
  in the tasks body. This is a light generative inference step — requires
  Sonnet-quality reasoning (hence R5-C dependency).
- `scope_implied` — thematic areas and intervention types described in the
  project scope / background section of the ToR.
- `explicit` — directly stated requirements: geography, years of experience,
  sector labels, donor-specific terminology.

### How it feeds into R5-B

The Python keyword scorer (`_keyword_score`) will consume the merged keyword
set from all three lists. `role_implied` and `scope_implied` are weighted
equally; `explicit` keywords receive a score bonus multiplier (TBD at
calibration). The full merged list is what appears in `keyword_matches` in
the pre-computed block injected into A3's prompt.

### Transparency and auditability

`scoring_keywords` is written to `tor_data.json` and therefore visible in
the session artifacts. A developer or reviewer can see exactly which keywords
drove the scoring for any given run — making the basis for project selection
explainable and auditable.

### A2 prompt changes

A new `### Scoring keywords` section to be added to `SYSTEM_PROMPT_A2`:
- Extract `explicit` keywords from stated requirements, geography, and experience
  thresholds.
- Extract `scope_implied` keywords from the project background and scope
  description.
- Infer `role_implied` keywords from the position title and pool name — terms a
  competent expert in this role would routinely work with, even if unstated.
- Each list should contain 5–15 keywords. Prefer specific technical terms over
  generic ones.

---

## Proposed interface (R5-B)

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
    }
  ],
  "scoring_note": "Scores computed by Python keyword-overlap before calling LLM."
}
```

The prompt update instructs the LLM:
- Use `composite_score` as the starting `relevance_score` for each project.
- Adjust ±0.10 based on semantic task/competency overlap not captured by
  keyword matching.
- Report adjusted score and reasoning in `project_scores`.

---

## Scoring algorithm design

### 1. Sector keyword match (35% weight)

With R5-A, `sector_keywords` is drawn from `tor_data["scoring_keywords"]`
(merged across all three lists) rather than from the tasks list alone.

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

Semantic matching requires an embedding model. Leave for LLM to assess —
instruct it to adjust the composite score based on task alignment.

When an embedding API becomes available:
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
# LLM adds the remaining 0.55 weight (tasks 0.30 + competencies 0.20)
# by adjusting composite within ±0.10
```

---

## Prompt update for A3 (when implemented)

Add to `SYSTEM_PROMPT_A3` after "## Scoring rules":

```
## Pre-computed scores
A `<pre_computed>` block is provided containing Python-computed keyword and
geography scores for each project. These are partial scores covering 50% of
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

1. **R5-A must land first** — `scoring_keywords` must be present in
   `tor_data.json` before R5-B's keyword scorer can consume it. Both fixes
   should be implemented in the same round.
2. **R5-C (Sonnet sweep) must land in the same round** — A2's role-implied
   keyword inference is a light generative step that requires Sonnet-quality
   reasoning. Haiku will produce shallow or generic `role_implied` lists.
3. **No embedding API currently wired** — task/competency semantic matching
   deferred. A bag-of-words approach via R5-A's keyword set partially
   compensates.
4. **Threshold calibration after R5-B** — R4-A's threshold constants
   (`0.30 / 0.40 / 0.50`) are interim values. Once Python scoring produces
   consistent scores, recalibrate thresholds against production runs.
5. **Regression testing required** — run a batch of existing sessions with
   and without pre-computed scores to verify project selection quality
   is maintained or improved.

---

## Files to modify when implementing

| File | Change |
|---|---|
| `pipeline/agents/tor_summarizer.py` | Add `scoring_keywords` to `DistilledToR` schema; extend `SYSTEM_PROMPT_A2` with keyword extraction section. |
| `pipeline/agents/cv_tor_mapper.py` | Replace `_precompute_relevance_scores` stub with real implementation; update `SYSTEM_PROMPT_A3` to add pre-computed score usage instructions. |
| `pipeline/precompute_utils.py` | Add `keyword_overlap_score`, `geography_score` helpers. |
| `models.py` | Add `ScoringKeywords` model and `scoring_keywords` field to `DistilledToR`. |
| `tests/test_tor_summarizer.py` | New tests for `scoring_keywords` extraction (role_implied, scope_implied, explicit). |
| `tests/test_precompute_utils.py` | Add tests for new scoring helpers. |
| `tests/test_cv_tor_mapper.py` | Verify pre-computed block is sent and scores are used. |

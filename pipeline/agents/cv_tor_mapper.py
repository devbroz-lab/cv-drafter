"""
Agent 3 — CV-to-ToR Mapper.

Scores each project in the extracted CVData for relevance to the DistilledToR,
drops low-relevance projects, and produces a filtered CVData alongside a
structured alignment report.

Input:  runs/{session_id}/cv_data.json + tor_data.json + manifest.json
Output: runs/{session_id}/mapped_cv.json
"""

from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from models import CVData
from pipeline.manifest import update_step
from pipeline.utils import resolve_tor_for_agents, strip_code_fences

client = Anthropic()

# Minimum number of projects guaranteed to survive filtering regardless of score.
MIN_PROJECTS_TO_KEEP: int = 2


# ---------------------------------------------------------------------------
# P2-A3 (DEFERRED): Python pre-compute for relevance scoring
# ---------------------------------------------------------------------------
# TODO(P2-A3): implement keyword-overlap relevance scoring in Python so the
# LLM selects-and-explains rather than calculates.  This stub currently returns
# None, which means the <pre_computed> block is NOT added to the user message
# and the existing LLM-side scoring logic continues unchanged.
#
# When implemented, _precompute_relevance_scores should return a dict like:
# {
#   "project_scores": [
#     {
#       "project_name": str,
#       "keyword_overlap_score": float,   # 0.0–1.0 — sector-keyword match
#       "country_overlap": list[str],     # matched countries from country_experience_required
#       "duration_years": float,          # Python-computed years
#     },
#     ...
#   ]
# }
# See additions/RELEVANCE_SCORING_DESIGN.md for the full design.

def _precompute_relevance_scores(cv_data: dict, tor_data: dict) -> dict | None:
    """
    Pre-compute per-project relevance signals for the mapper agent.

    Returns None until the full implementation is complete (see TODO above).
    When this returns non-None, the caller will include a <pre_computed> block
    in the user message so the LLM selects and explains rather than calculates.
    """
    # TODO(P2-A3): replace with real implementation
    return None


SYSTEM_PROMPT_A3 = """
You are the CV to ToR Mapper agent in a document processing pipeline. You
receive a fully extracted CVData object and a DistilledToR object. Your job
is to score each project in the CV for relevance to the ToR, decide which
projects to keep, and produce a filtered CVData alongside a structured
alignment report.

## Output rules
- Respond with a single JSON object and nothing else.
- No preamble, no explanation, no markdown fences.
- The output must conform exactly to this structure:

{
  "data": { ...CVData object with filtered relevant_projects... },
  "alignment": {
    "kept_sections": [...],
    "dropped_sections": [...],
    "project_scores": [
      {
        "project_name": "...",
        "relevance_score": 0.0,
        "matched_keywords": [...],
        "matched_tasks": [...],
        "matched_competencies": [...],
        "matched_geography": [...],
        "kept": true
      }
    ],
    "warnings": [...]
  }
}

## Scoring rules

### What to score
- Score every RelevantProject entry in the CVData.
- Do NOT score Education, Languages, or CountryExperience — those are always
  kept in full.

### How to score
Assign each project a relevance_score between 0.0 and 1.0 based on how well
it matches the DistilledToR across four dimensions. Weight them as follows:

  1. Sector keywords match     — 35%
     How many of DistilledToR.sector_keywords appear in the project's
     main_project_features, activities_performed, and positions_held fields.

  2. Key tasks match           — 30%
     How closely the project's activities_performed aligns with
     DistilledToR.key_tasks. Partial matches count — look for semantic
     overlap, not just exact string matches.

  3. Competencies match        — 20%
     How many required_competencies and preferred_competencies are evidenced
     by the project's positions_held and activities_performed.
     Weight required_competencies twice as heavily as preferred.

  4. Geography match           — 15%
     Whether the project's location or `country` field matches any entry in
     DistilledToR.country_experience_required (the canonical list of required
     or preferred countries/regions).
     Exact country name match = full weight.
     Same region or partial name overlap = half weight.
     No match = zero for this dimension.
     Note: DistilledToR.geography is a short human-readable display string and
     is NOT used for scoring — always use country_experience_required.

### Threshold and minimum guarantee
- After scoring all projects, determine a dynamic threshold:
    - If total projects <= 5:  threshold = 0.40
    - If total projects 6–10:  threshold = 0.50
    - If total projects > 10:  threshold = 0.60
- Drop all projects below the threshold.
- Exception: always keep the top N projects by score, even if they fall
  below the threshold. N is provided in the input as `min_projects_to_keep`.
  If `min_projects_to_keep` is not present in `<params>`, default to 2.
- Set `kept: true` for surviving projects, `kept: false` for dropped ones.
- Include ALL projects (kept and dropped) in `project_scores` for the
  alignment report.

### kept_sections and dropped_sections
- `kept_sections`: list the CVData top-level fields that have at least one
  non-empty value after filtering — e.g. ["relevant_projects", "education",
  "languages", "countries_of_experience"].
- `dropped_sections`: list any top-level fields that were non-empty in the
  input CVData but are empty after filtering.
  Note: if `employment_record` is [] in the input, do not list it as dropped —
  it was never populated. If it is non-empty in the input, pass it through
  unchanged and do NOT list it in dropped_sections.

### warnings
- Add a warning string for any of the following conditions:
    - Fewer than `min_projects_to_keep` projects survived above the threshold
      before the minimum guarantee was applied.
    - More than half of all projects were dropped.
    - No geography matches were found across any project.
    - No sector keyword matches were found across any project.
- Leave as [] if none of these conditions apply.

## Strict rules
- Do NOT modify any field values in the CVData. Copy them exactly as received.
- Do NOT add, infer, or generate any content.
- The `data` block must be a valid CVData object.
- Only `relevant_projects` changes between input and output — it contains
  only the kept projects, in their original order.
- Every other CVData field — including `employment_record`, `education`,
  `languages`, `countries_of_experience`, `key_qualifications`, `certifications`,
  and all personal info — must be copied to the output exactly as received.
  Never empty a field that was non-empty in the input.

## Inputs
The user message will contain:
  <cv_data>   — the full CVData JSON from cv_data.json     </cv_data>
  <tor_data>  — the full DistilledToR JSON from tor_data.json  </tor_data>
  <params>    — pipeline params including min_projects_to_keep  </params>
"""


def run(run_dir: Path) -> dict:
    """
    Read cv_data.json, tor_data.json, and manifest from run_dir, call the
    mapper agent, and write mapped_cv.json.

    Returns:
        The parsed output dict containing 'data' (CVData) and 'alignment'.
    """
    update_step(run_dir, "cv_tor_mapper", "running")

    cv_raw = json.loads((run_dir / "cv_data.json").read_text(encoding="utf-8"))
    tor_raw = json.loads((run_dir / "tor_data.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    cv_data = cv_raw["data"]
    tor_data = resolve_tor_for_agents(tor_raw, context="cv_tor_mapper.run")
    params = manifest["params"]

    pre_computed = _precompute_relevance_scores(cv_data, tor_data)

    user_message = (
        f"<cv_data>\n{json.dumps(cv_data, indent=2)}\n</cv_data>\n\n"
        f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
        "<params>\n"
        + json.dumps({"min_projects_to_keep": MIN_PROJECTS_TO_KEEP, **params}, indent=2)
        + "\n</params>"
        + (
            f"\n\n<pre_computed>\n{json.dumps(pre_computed, indent=2)}\n</pre_computed>"
            if pre_computed is not None
            else ""
        )
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=SYSTEM_PROMPT_A3,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "cv_tor_mapper", "failed")
        raise ValueError("CV-ToR Mapper response truncated (max_tokens reached).")

    raw = strip_code_fences(response.content[0].text.strip())

    try:
        parsed = json.loads(raw)
        CVData.model_validate(parsed["data"])
        alignment = parsed["alignment"]
        assert "kept_sections" in alignment
        assert "dropped_sections" in alignment
        assert "project_scores" in alignment
        assert "warnings" in alignment
    except Exception as exc:
        update_step(run_dir, "cv_tor_mapper", "failed")
        raise ValueError(
            f"CV-ToR Mapper returned invalid output: {exc}\n\nRaw output:\n{raw}"
        ) from exc

    output = {
        "approved": False,
        "approved_at": None,
        **parsed,  # contains "data" and "alignment"
    }
    (run_dir / "mapped_cv.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    update_step(run_dir, "cv_tor_mapper", "done")
    return parsed

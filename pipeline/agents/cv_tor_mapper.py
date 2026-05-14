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
from pipeline.config import ANTHROPIC_MODEL
from pipeline.manifest import update_step
from pipeline.precompute_utils import (
    compute_composite_score,
    compute_project_duration,
    compute_project_year,
    geography_score,
    keyword_overlap_score,
)
from pipeline.utils import extract_json_object, resolve_tor_for_agents, strip_code_fences

client = Anthropic()

# Minimum number of projects guaranteed to survive filtering regardless of score.
# A dynamic floor of min(MIN_PROJECTS_TO_KEEP, total_projects) is applied inside
# _enforce_threshold_and_cap to avoid restoring non-existent projects on thin CVs.
MIN_PROJECTS_TO_KEEP: int = 5

# Maximum number of projects passed to Agent 4.
# Fix 8 Parts 2 and 3 (per-project text cap + prompt priority order) now protect
# A4's token budget independently of project count, so this cap is raised to
# preserve CV completeness for candidates with rich, relevant histories.
# These constants are interim values pending Fix 4 (Python relevance scoring).
MAX_PROJECTS_TO_KEEP: int = 15


# ---------------------------------------------------------------------------
# Fix 4 — Python pre-compute for relevance scoring (Round 5)
# ---------------------------------------------------------------------------


def _precompute_project_dates_for_mapper(cv_data: dict) -> dict:
    """
    Walk cv_data["relevant_projects"] and pre-fill empty ``duration`` and
    ``year`` fields before passing to the mapper LLM.

    This function was moved upstream from ``fields_generator.py`` in Round 5
    so that Agent 3 can see ``duration`` as a scoring signal.

    Only fills fields that are currently empty string "".  Never overwrites
    a non-empty value.

    Returns a shallow-copied cv_data dict with the updated projects list.
    """
    import copy
    result = copy.deepcopy(cv_data)
    for project in result.get("relevant_projects", []):
        date_from = project.get("date_from", "")
        date_to = project.get("date_to", "")

        if not project.get("duration", ""):
            computed = compute_project_duration(date_from, date_to)
            if computed:
                project["duration"] = computed

        if not project.get("year", ""):
            computed = compute_project_year(date_from, date_to)
            if computed:
                project["year"] = computed

    return result


def _compute_threshold(total_projects: int) -> float:
    """
    Return the dynamic relevance threshold for the given project count.

    Mirrors the rule in SYSTEM_PROMPT_A3 so Python enforcement uses the
    same thresholds the LLM is instructed to apply.

    Thresholds reduced by 0.10 vs Round 2 values to retain borderline-relevant
    projects (0.35–0.50 range) that represent genuine experience and were being
    discarded under the previous calibration.  These values are interim pending
    Fix 4 (Python relevance scoring).
    """
    if total_projects <= 5:
        return 0.30
    if total_projects <= 10:
        return 0.40
    return 0.50


def _enforce_threshold_and_cap(parsed: dict, original_projects: list[dict]) -> None:
    """
    In-place post-processing on the LLM-returned ``parsed`` dict.

    Applies in sequence:
      1. Threshold enforcement — drop any project the LLM marked ``kept=True``
         but whose ``relevance_score`` falls below the dynamic threshold.
      2. Minimum guarantee — restore the top-scoring dropped projects until at
         least MIN_PROJECTS_TO_KEEP are kept.
      3. Maximum cap — if more than MAX_PROJECTS_TO_KEEP are kept, drop the
         lowest-scoring excess projects.
      4. Rebuild ``parsed["data"]["relevant_projects"]`` from the final kept
         set, preserving the original CV document order.
      5. Append warning strings to ``parsed["alignment"]["warnings"]`` for
         each enforcement action taken.

    ``original_projects`` is the list of project dicts from the input CV data
    (used to reconstruct CV document order in the output).
    """
    scores: list[dict] = parsed["alignment"]["project_scores"]
    warnings: list[str] = parsed["alignment"]["warnings"]
    total = len(scores)
    if total == 0:
        return

    threshold = _compute_threshold(total)

    # Dynamic floor: clamp minimum guarantee to the number of available projects
    # so we never attempt to restore projects that don't exist on thin CVs.
    effective_floor = min(MIN_PROJECTS_TO_KEEP, total)

    # --- Step 1: threshold enforcement ---
    dropped_by_threshold: list[str] = []
    for entry in scores:
        if entry.get("kept") and entry.get("relevance_score", 0.0) < threshold:
            entry["kept"] = False
            dropped_by_threshold.append(entry.get("project_name", "?"))

    if dropped_by_threshold:
        warnings.append(
            f"Python post-processing dropped {len(dropped_by_threshold)} project(s) "
            f"scored below the {threshold:.2f} threshold that the LLM had marked kept: "
            + ", ".join(dropped_by_threshold)
        )

    # --- Step 2: minimum guarantee (clamped to effective_floor) ---
    kept_count = sum(1 for e in scores if e.get("kept"))
    if kept_count < effective_floor:
        # Restore top-scoring dropped projects until we hit the minimum
        dropped_sorted = sorted(
            [e for e in scores if not e.get("kept")],
            key=lambda e: e.get("relevance_score", 0.0),
            reverse=True,
        )
        restored: list[str] = []
        for entry in dropped_sorted:
            if kept_count >= effective_floor:
                break
            entry["kept"] = True
            kept_count += 1
            restored.append(entry.get("project_name", "?"))

        if restored:
            warnings.append(
                f"Python post-processing restored {len(restored)} project(s) via "
                f"minimum-guarantee (effective_floor={effective_floor}): "
                + ", ".join(restored)
            )

    # --- Step 3: maximum cap ---
    kept_entries = [e for e in scores if e.get("kept")]
    if len(kept_entries) > MAX_PROJECTS_TO_KEEP:
        # Sort by score descending; drop the tail
        kept_sorted = sorted(
            kept_entries,
            key=lambda e: e.get("relevance_score", 0.0),
            reverse=True,
        )
        capped_names = [e.get("project_name", "?") for e in kept_sorted[MAX_PROJECTS_TO_KEEP:]]
        # Build a set of names to drop (handle rare duplicate names by index)
        to_drop = list(kept_sorted[MAX_PROJECTS_TO_KEEP:])
        to_drop_ids = {id(e) for e in to_drop}
        for entry in scores:
            if id(entry) in to_drop_ids:
                entry["kept"] = False

        warnings.append(
            f"Python post-processing capped kept projects at "
            f"MAX_PROJECTS_TO_KEEP={MAX_PROJECTS_TO_KEEP} "
            f"({len(capped_names)} project(s) truncated by score): "
            + ", ".join(capped_names)
        )

    # --- Step 4: rebuild data.relevant_projects in original CV order ---
    final_kept_names: set[str] = {
        e.get("project_name", "") for e in scores if e.get("kept")
    }
    # Preserve original document order; match by project_name
    parsed["data"]["relevant_projects"] = [
        proj for proj in original_projects
        if proj.get("project_name", "") in final_kept_names
    ]


def _precompute_relevance_scores(cv_data: dict, tor_data: dict) -> dict | None:
    """
    Pre-compute per-project relevance signals for Agent 3 (CV-ToR Mapper).

    Returns a dict that is injected as a ``<pre_computed>`` block into A3's
    user message.  The LLM uses ``composite_score`` as a starting
    ``relevance_score`` for each project and adjusts by ±0.10 based on its
    semantic assessment of task and competency alignment.

    Scoring dimensions (50% Python-computed; 50% LLM-assessed):
    - Keyword overlap  35%  — ``scoring_keywords`` from ``tor_data``
    - Geography match  15%  — ``country_experience_required`` from ``tor_data``
    - Key tasks        30%  — LLM semantic (not computed here)
    - Competencies     20%  — LLM semantic (not computed here)

    Returns ``None`` only when both the keyword list and required-countries
    list are empty (no scoring signal available) to preserve legacy behaviour.
    """
    # Merge all three keyword lists from scoring_keywords block
    sk = tor_data.get("scoring_keywords", {})
    merged_keywords: list[str] = (
        sk.get("role_implied", []) +
        sk.get("scope_implied", []) +
        sk.get("explicit", [])
    )

    # Fall back to legacy sector_keywords if scoring_keywords not present
    if not merged_keywords:
        merged_keywords = tor_data.get("sector_keywords", [])

    required_countries: list[str] = tor_data.get("country_experience_required", [])

    # No scoring signal available — return None to preserve legacy A3 behaviour
    if not merged_keywords and not required_countries:
        return None

    project_scores: list[dict] = []
    for project in cv_data.get("relevant_projects", []):
        kw_score, kw_matches = keyword_overlap_score(project, merged_keywords)
        geo_score, geo_matches = geography_score(project, required_countries)
        composite = compute_composite_score(kw_score, geo_score)

        # Compute duration_years for informational display in the pre-computed block
        duration_str = project.get("duration", "")
        try:
            duration_years = float(duration_str.split()[0]) if duration_str else 0.0
        except (ValueError, IndexError):
            duration_years = 0.0

        project_scores.append({
            "project_name": project.get("project_name", ""),
            "keyword_overlap_score": round(kw_score, 4),
            "keyword_matches": kw_matches,
            "country_overlap": geo_matches,
            "duration_years": duration_years,
            "composite_score": composite,
        })

    return {
        "project_scores": project_scores,
        "scoring_note": (
            "Scores computed by Python keyword-overlap and geography-match "
            "before calling LLM.  composite_score covers 50% of total weight "
            "(keyword 35% + geography 15%).  LLM adjusts within ±0.10."
        ),
    }


SYSTEM_PROMPT_A3 = """
You are the CV to ToR Mapper agent in a document processing pipeline. You
receive a fully extracted CVData object and a DistilledToR object. Your job
is to score each project in the CV for relevance to the ToR, decide which
projects to keep, and produce a filtered CVData alongside a structured
alignment report.

## Output contract (READ FIRST)
- Your entire response must be a single JSON object — nothing else.
- The FIRST non-whitespace character MUST be `{`. The LAST MUST be `}`.
- No preamble. No reasoning text. No "Here is the JSON". No explanation.
- No markdown fences (no ```json, no ```).
- Do all reasoning silently. Only the JSON object is emitted.
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
    - If total projects <= 5:  threshold = 0.30
    - If total projects 6–10:  threshold = 0.40
    - If total projects > 10:  threshold = 0.50
- Drop all projects below the threshold.
- Exception: always keep the top N projects by score, even if they fall
  below the threshold. N is provided in the input as `min_projects_to_keep`.
  If `min_projects_to_keep` is not present in `<params>`, default to 3.
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

## Pre-computed scores

When a `<pre_computed>` block is present in the user message, it contains
Python-computed keyword and geography scores for each project covering 50%
of the total scoring weight.

Use them as follows:
- Start from ``composite_score`` as the base for each project's
  ``relevance_score``.
- Adjust by up to ±0.10 based on your semantic assessment of task and
  competency alignment (the remaining 50% weight).
- Report your final adjusted ``relevance_score`` and include the
  ``keyword_matches`` and ``country_overlap`` lists in your
  ``project_scores`` output.
- Do NOT discard or ignore the pre-computed scores — they are a reliable
  Python-computed baseline; your role is to adjust for semantic alignment
  not captured by keyword matching.

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

    # Fix 4 (Round 5): pre-fill project duration and year before A3 sees the data.
    # Moved upstream from fields_generator.py so A3's LLM can use duration as a
    # scoring signal for long-term vs short-term assignment weighting.
    cv_data = _precompute_project_dates_for_mapper(cv_data)

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
        model=ANTHROPIC_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT_A3,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "cv_tor_mapper", "failed")
        raise ValueError("CV-ToR Mapper response truncated (max_tokens reached).")

    raw = strip_code_fences(response.content[0].text.strip())
    raw = extract_json_object(raw)

    try:
        parsed = json.loads(raw)
        alignment = parsed["alignment"]
        assert "kept_sections" in alignment
        assert "dropped_sections" in alignment
        assert "project_scores" in alignment
        assert "warnings" in alignment

        # Fix J + Fix 8 Part 1: Python enforcement of threshold and project cap.
        # Must run BEFORE CVData.model_validate so the corrected data is validated.
        _enforce_threshold_and_cap(parsed, cv_data.get("relevant_projects", []))

        CVData.model_validate(parsed["data"])
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

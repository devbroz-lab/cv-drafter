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
from pipeline.utils import strip_code_fences

client = Anthropic()

# Minimum number of projects guaranteed to survive filtering regardless of score.
MIN_PROJECTS_TO_KEEP: int = 2

SYSTEM_PROMPT = """
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
- Do NOT score Education, Languages, or CountryExperience — those are always kept.

### How to score
Assign each project a relevance_score between 0.0 and 1.0:
  1. Sector keywords match     — 35%
  2. Key tasks match           — 30%
  3. Competencies match        — 20%
  4. Geography match           — 15%

### Threshold and minimum guarantee
- Dynamic threshold: <=5 projects -> 0.40 | 6-10 -> 0.50 | >10 -> 0.60
- Always keep the top N projects by score (N = min_projects_to_keep from params).
- Include ALL projects in project_scores (kept and dropped).

### Strict rules
- Do NOT modify any field values in the CVData. Copy them exactly as received.
- Only `relevant_projects` changes between input and output.
- All other CVData fields are passed through unchanged.

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
    tor_data = tor_raw["data"]
    params = manifest["params"]

    user_message = (
        f"<cv_data>\n{json.dumps(cv_data, indent=2)}\n</cv_data>\n\n"
        f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
        "<params>\n"
        + json.dumps({"min_projects_to_keep": MIN_PROJECTS_TO_KEEP, **params}, indent=2)
        + "\n</params>"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
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

"""
Agent 6 — Compressor.

Shortens compressible CVData fields to bring the total word count within the
page-limit target.  Protected fields (personal info, education, languages, etc.)
are never touched.

Input:  runs/{session_id}/generated_fields.json + tor_data.json + manifest.json
Output: updates generated_fields.json (adds "compression" block, updates "generated")
"""

from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from models import CVData
from pipeline.manifest import update_step
from pipeline.utils import strip_code_fences

client = Anthropic()

# Fields that must NEVER be passed to compression logic.
PROTECTED_FIELDS: frozenset[str] = frozenset(
    {
        "personal_info",
        "education",
        "languages",
        "countries_of_experience",
        "certifications",
        "membership_professional_bodies",
        "present_position",
        "proposed_position",
        "category",
        "employer",
        "years_with_firm",
        "world_bank_affiliation",
    }
)

SYSTEM_PROMPT = """
You are the Compressor agent in a document processing pipeline. You receive
a reviewed CVData object and compression instructions. Your job is to shorten
content across the CVData to bring the total word count within the specified
target, while preserving meaning, accuracy, and tone.

## Output rules
- Respond with a single JSON object and nothing else.
- No preamble, no explanation, no markdown fences.
- The output must have this exact shape:

{
  "data": { ...full CVData object with compressed content... },
  "compression": {
    "applied": true,
    "words_before": 0,
    "words_after": 0,
    "target_words": 0,
    "ratio_applied": false,
    "fields_shortened": [
      {
        "field": "...",
        "subfield": "...",
        "words_before": 0,
        "words_after": 0
      }
    ]
  }
}

- If no compression was needed (words_before <= target_words),
  set `applied` to false, return the CVData unchanged, and leave
  `fields_shortened` as [].

## Compression rules
- Never remove a sector keyword from DistilledToR.sector_keywords.
- Never change a date, number, proper noun, or country name.
- Never merge two separate projects into one.
- Never remove an entire GeneratedField item — shorten it instead.
- Never alter meaning — compression must be loss of words, not loss of facts.
- Maintain active voice and action verbs throughout.
- Apply cuts proportionally across projects.

## Protected fields — never compress
personal_info, education, languages, countries_of_experience, certifications,
membership_professional_bodies, present_position, proposed_position,
category, employer, years_with_firm, world_bank_affiliation.

## Compressible fields only
- relevant_projects: activities_performed, main_project_features
- generated_fields: content (for each GeneratedField item)
- key_qualifications (extracted list on CVData)
- other_relevant_info
- other_skills (each item)
- publications (each item)

## Compression priority
1. Remove redundancy
2. Tighten verbose constructions
3. Trim supporting detail
4. Shorten long project descriptions (>60 words)

## Inputs
The user message will contain:
  <cv_data>            — reviewed CVData from generated_fields.json   </cv_data>
  <tor_data>           — DistilledToR (for sector_keywords reference) </tor_data>
  <compression_params> — target_words, compression_ratio              </compression_params>
"""


def _count_compressible_words(cv_data: dict) -> int:
    """Count words across compressible fields only (mirrors the LLM's definition)."""

    def words(s: str) -> int:
        return len(s.split()) if s else 0

    total = 0
    for proj in cv_data.get("relevant_projects", []):
        total += words(proj.get("activities_performed", ""))
        total += words(proj.get("main_project_features", ""))
    for gf in cv_data.get("generated_fields", []):
        total += words(gf.get("content", ""))
    for item in cv_data.get("key_qualifications", []):
        total += words(item)
    total += words(cv_data.get("other_relevant_info", ""))
    for item in cv_data.get("other_skills", []):
        total += words(item)
    for item in cv_data.get("publications", []):
        total += words(item)
    return total


def run(
    run_dir: Path,
    target_words: int = 0,
    compression_ratio: float = 0.80,
) -> CVData:
    """
    Compress compressible CVData fields to meet the page-limit target and
    write the compression block back to generated_fields.json.

    Args:
        run_dir:          Path to the session run directory.
        target_words:     Hard word-count target (0 = use compression_ratio).
        compression_ratio: Fallback ratio when target_words is 0 (default 0.80).

    Returns:
        Validated (possibly compressed) CVData instance.
    """
    update_step(run_dir, "compressor", "running")

    gf_path = run_dir / "generated_fields.json"
    gf_raw = json.loads(gf_path.read_text(encoding="utf-8"))
    cv_data_in = gf_raw["generated"]
    tor_data = json.loads((run_dir / "tor_data.json").read_text(encoding="utf-8"))["data"]

    current_words = _count_compressible_words(cv_data_in)
    effective_target = target_words if target_words > 0 else int(current_words * compression_ratio)

    # Skip LLM call if already within target
    if current_words <= effective_target:
        gf_raw["compression"] = {
            "applied": False,
            "words_before": current_words,
            "words_after": current_words,
            "target_words": effective_target,
            "ratio_applied": target_words == 0,
            "fields_shortened": [],
        }
        gf_path.write_text(json.dumps(gf_raw, indent=2, ensure_ascii=False), encoding="utf-8")
        update_step(run_dir, "compressor", "done")
        return CVData.model_validate(cv_data_in)

    compression_params = {
        "target_words": effective_target,
        "compression_ratio": compression_ratio,
        "words_before": current_words,
    }

    user_message = (
        f"<cv_data>\n{json.dumps(cv_data_in, indent=2)}\n</cv_data>\n\n"
        f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
        f"<compression_params>\n{json.dumps(compression_params, indent=2)}\n</compression_params>"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "compressor", "failed")
        raise ValueError("Compressor response truncated (max_tokens reached).")

    raw = strip_code_fences(response.content[0].text.strip())

    try:
        parsed = json.loads(raw)
        cv_data_out = CVData.model_validate(parsed["data"])
        compression = parsed["compression"]
        assert "applied" in compression
        assert "words_before" in compression
        assert "words_after" in compression
        assert "fields_shortened" in compression
    except Exception as exc:
        update_step(run_dir, "compressor", "failed")
        raise ValueError(f"Compressor returned invalid output: {exc}\n\nRaw:\n{raw}") from exc

    gf_raw["generated"] = cv_data_out.model_dump()
    gf_raw["compression"] = compression
    gf_path.write_text(json.dumps(gf_raw, indent=2, ensure_ascii=False), encoding="utf-8")

    update_step(run_dir, "compressor", "done")
    return cv_data_out

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

from models import CompressionResult, CVData
from pipeline.manifest import update_step
from pipeline.precompute_utils import (
    count_compressible_words_total,
    count_words_per_field,
    restore_protected_fields,
)
from pipeline.utils import resolve_tor_for_agents, strip_code_fences

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


SYSTEM_PROMPT_A6 = """
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
    "target_not_reached": false,
    "fields_shortened": [
      {
        "field": "...",
        "subfield": "...",
        "words_before": 0,
        "words_after": 0
      }
    ]
  },
  "generation_warnings": []
}

- If no compression was needed (words_before <= target_words),
  set `applied` to false, return the CVData unchanged, and leave
  `fields_shortened` as [].

## Compression instructions

### Primary target — word count
You will receive `target_words` in `<compression_params>`. Reduce the total
word count of all compressible content to at or below this target.

### Fallback — compression ratio
If `target_words` is not provided or is 0, apply the `compression_ratio`
from `<compression_params>` instead.
Example: compression_ratio = 0.80 means reduce total compressible word
count to 80% of its current value.

### How to compress — priorities
Compress simultaneously across projects and generated_fields, prioritising
the least impactful cuts first:

Priority 1 — Remove redundancy
  Remove repeated ideas, synonymous phrases, and restated conclusions.
  Example: "Conducted analysis and performed analytical work" → "Conducted analysis"

Priority 2 — Tighten verbose constructions
  Replace wordy phrases with concise equivalents.
  Examples:
  - "in order to" → "to"
  - "as a result of" → "due to"
  - "a large number of" → "many"
  - "with the aim of achieving" → "to achieve"

Priority 3 — Trim supporting detail
  Remove illustrative examples, parenthetical clarifications, and
  elaborations that restate the main point.
  Keep: the core claim, the action, the outcome.
  Remove: "for example", "such as X and Y", "including but not limited to"

Priority 4 — Shorten long project descriptions
  If activities_performed or main_project_features exceed 60 words,
  reduce to the single most impactful sentence or clause per activity.
  Preserve all sector keywords from DistilledToR.sector_keywords.

### Compression rules
- Never remove a sector keyword from DistilledToR.sector_keywords.
- Never change a date, number, proper noun, or country name.
- Never merge two separate projects into one.
- Never remove an entire GeneratedField item — shorten it instead.
- Never alter meaning — compression must be loss of words, not loss of facts.
- Maintain active voice and action verbs throughout.
- Apply cuts proportionally across projects — do not strip one project
  bare while leaving others untouched.

### When target cannot be reached
If you cannot reach `target_words` without violating the rules above
(e.g. removing a GeneratedField item, changing a proper noun, altering a
sector keyword), compress as much as possible within the rules and set
`compression.target_not_reached` to true in your output. Do not violate
the rules in order to hit the number.

## Protected fields — never compress
The following fields must not be compressed or paraphrased. Return them
exactly as received. The pipeline will restore any protected field that
was inadvertently altered — do not alter them intentionally.
- personal_info (all subfields)
- education (all subfields)
- languages (all subfields)
- countries_of_experience (all subfields)
- certifications
- membership_professional_bodies
- present_position
- proposed_position
- category
- employer
- years_with_firm
- world_bank_affiliation

## Compressible fields
Only these fields are eligible for compression:
- relevant_projects: activities_performed, main_project_features
  (date_from, date_to, location, client, company, donor, positions_held,
  project_name, duration, year are all protected within each project)
- employment_record: description
  (from_date, to_date, employer, positions_held, location, country are all
  protected within each entry — only the narrative description is compressible)
- generated_fields: content (for each GeneratedField item)
- key_qualifications (extracted list on CVData)
- other_relevant_info
- other_skills (each item)
- training (each item)
- publications (each item)

## Word counting
You are provided with `words_before` and `words_per_field` in
`<compression_params>`. These were computed by the pipeline before calling
you.

- Copy `words_before` directly into your `compression.words_before` output
  field — do not recount.
- Your reported `words_after` is an estimate based on your own compression.
  The pipeline will compute the authoritative post-compression count from
  the actual output JSON and overwrite your estimate — so a close
  approximation is sufficient.

## generation_warnings passthrough
The `generation_warnings` list from the prior pipeline step is supplied in
`<generation_warnings>`. Copy it unchanged into the top-level
`generation_warnings` key of your output. Do not modify, add to, or
remove from this list.

## Inputs
The user message will contain:
  <cv_data>             — reviewed CVData from generated_fields.json        </cv_data>
  <tor_data>            — DistilledToR (for sector_keywords reference)      </tor_data>
  <compression_params>  — target_words, compression_ratio, words_before,
                          words_per_field                                   </compression_params>
  <generation_warnings> — warnings passthrough from Agent 4                 </generation_warnings>
"""

def _count_compressible_words(cv_data: dict) -> int:
    """
    Count words across compressible fields only.

    Thin wrapper over the shared utility so existing callers continue to work.
    """
    return count_compressible_words_total(cv_data)


def run(
    run_dir: Path,
    target_words: int = 0,
    compression_ratio: float = 0.80,
) -> CVData:
    """
    Compress compressible CVData fields to meet the page-limit target and
    write the compression block back to generated_fields.json.

    Changes vs. original implementation:
    - P16: words_before and per-field counts pre-computed in Python and passed
           into <compression_params>; authoritative words_after computed post-response.
    - P17: prompt no longer says "character for character"; Python restores any
           protected fields the LLM inadvertently altered.
    - P18: compression block now includes target_not_reached flag.
    - P19: generation_warnings are read from generated_fields.json and passed
           through to the output unchanged.
    - CompressionResult Pydantic model replaces raw dict assert checks.

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
    # P19: read generation_warnings from file; pass through unchanged
    generation_warnings = gf_raw.get("generation_warnings", [])

    tor_raw = json.loads((run_dir / "tor_data.json").read_text(encoding="utf-8"))
    tor_data = resolve_tor_for_agents(tor_raw, context="compressor.run")

    # P16/P2-A6: pre-compute word counts in Python
    words_per_field = count_words_per_field(cv_data_in)
    current_words = sum(words_per_field.values())
    effective_target = target_words if target_words > 0 else int(current_words * compression_ratio)

    # Skip LLM call if already within target
    if current_words <= effective_target:
        compression_result = CompressionResult(
            applied=False,
            words_before=current_words,
            words_after=current_words,
            target_words=effective_target,
            ratio_applied=target_words == 0,
            fields_shortened=[],
        )
        gf_raw["compression"] = compression_result.model_dump()
        gf_raw["generation_warnings"] = generation_warnings
        gf_path.write_text(json.dumps(gf_raw, indent=2, ensure_ascii=False), encoding="utf-8")
        update_step(run_dir, "compressor", "done")
        return CVData.model_validate(cv_data_in)

    # P16: pass pre-computed counts into <compression_params>
    compression_params = {
        "target_words": effective_target,
        "compression_ratio": compression_ratio,
        "words_before": current_words,
        "words_per_field": words_per_field,
    }

    user_message = (
        f"<cv_data>\n{json.dumps(cv_data_in, indent=2)}\n</cv_data>\n\n"
        f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
        f"<compression_params>\n{json.dumps(compression_params, indent=2)}\n</compression_params>\n\n"
        f"<generation_warnings>\n{json.dumps(generation_warnings, indent=2)}\n</generation_warnings>"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=SYSTEM_PROMPT_A6,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "compressor", "failed")
        raise ValueError("Compressor response truncated (max_tokens reached).")

    raw = strip_code_fences(response.content[0].text.strip())

    try:
        parsed = json.loads(raw)
        cv_data_out_raw = parsed["data"]
        compression_raw = parsed["compression"]
        # P18: accept target_not_reached from LLM (defaults False if absent)
        compression_result = CompressionResult.model_validate(compression_raw)
    except Exception as exc:
        update_step(run_dir, "compressor", "failed")
        raise ValueError(f"Compressor returned invalid output: {exc}\n\nRaw:\n{raw}") from exc

    # P16 (post-compute): overwrite LLM's estimated words_after with authoritative count
    compression_result.words_after = count_compressible_words_total(cv_data_out_raw)
    # Also enforce the Python-computed words_before (the LLM was told to copy it,
    # but we overwrite here regardless to guarantee accuracy)
    compression_result.words_before = current_words

    # P17 (post-compute): restore any protected fields the LLM inadvertently altered
    restored_data, restored_paths = restore_protected_fields(
        cv_data_in, cv_data_out_raw, PROTECTED_FIELDS
    )
    if restored_paths:
        compression_result.protected_field_restorations = restored_paths

    cv_data_out = CVData.model_validate(restored_data)

    gf_raw["generated"] = cv_data_out.model_dump()
    gf_raw["compression"] = compression_result.model_dump()
    # P19: write generation_warnings passthrough back to file
    gf_raw["generation_warnings"] = generation_warnings
    gf_path.write_text(json.dumps(gf_raw, indent=2, ensure_ascii=False), encoding="utf-8")

    update_step(run_dir, "compressor", "done")
    return cv_data_out

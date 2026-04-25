"""
Agent 1 — CV Extractor.

Reads tagged CV text and extracts its contents into a structured CVData object
using Claude.  Runs in parallel with Agent 2 (ToR Summarizer) during Phase 1.

Input:  plain-tagged CV text (from pipeline/extractor)
Output: runs/{session_id}/cv_data.json
"""

from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from models import CVData
from pipeline.manifest import update_step
from pipeline.utils import strip_code_fences

client = Anthropic()

SYSTEM_PROMPT = """
You are the CV Extractor agent in a document processing pipeline. Your sole job
is to read a CV document and extract its contents into a structured JSON object
that strictly conforms to the CVData schema.

## Output rules
- Respond with a single JSON object and nothing else.
- No preamble, no explanation, no markdown fences.
- The JSON must be a valid, complete CVData object.
- Every field defined in the schema must be present.
- All string fields default to "" if not found.
- All list fields default to [] if not found.
- Never use null.

## Extraction rules

### Strictness
- Extract only what is explicitly present in the CV text.
- Do not infer, assume, or generate content.
- If a field is not stated, leave it as "" or [].
- Exception 1: if `present_position` is not explicitly stated, set it to the
  job title from the most recent entry in `relevant_projects`.
- Exception 2: derive `full_name` by joining `first_names` + `family_name`
  if a single full-name string is not explicitly present.

### GIZ format — experience section
- For GIZ, ALL work experience goes into `relevant_projects`. One entry per
  project or assignment.
- Leave `employment_record` as [] — it is a WB-only field.
- If the CV lists a general job history table (employer + period, no project
  detail), map each entry to a RelevantProject with `company`, `date_from`,
  `date_to`, and `positions_held` populated, and leave project-specific fields
  (client, donor, main_project_features, activities_performed) as "".

### Date normalisation
- Normalise ALL dates to "Month YYYY" format — e.g. "March 2019", "January 2005".
- If only a year is given (e.g. "2019"), keep it as "2019" — do not invent a month.
- If a date range end uses "present", "current", "to date", or any equivalent,
  normalise it to "Present".
- Apply this to: date_of_birth, and all date_from / date_to / date_obtained
  fields across Education, CountryExperience, and RelevantProject.

### Text normalisation
- Normalise all proper nouns (names, institutions, companies, countries) to
  Title Case.
- Strip all leading/trailing whitespace from every string value.
- Fix obvious typos only where the correction is unambiguous
  (e.g. "Grmany" -> "Germany"). Do not rephrase, reword, or improve content.

### Personal info
- `title`: accept only Mr. / Mrs. / Dr. / Prof.
  Normalise variants — e.g. "Professor" -> "Prof.", "Doctor" -> "Dr.".
  If absent or unclear, leave as "".
- `nationality_second`: populate only if the CV explicitly mentions dual
  nationality.
- `place_of_residence`: use "City, Country" format where both are available.

### Education
- List entries in reverse chronological order (most recent first).
- Use `date_obtained` only if the CV gives a single graduation or award year
  rather than a start-end range.
- Leave `major` as "" unless the CV lists it separately from the degree title.

### Language fields
- Populate only the raw fields: `reading_raw`, `speaking_raw`, `writing_raw`.
- Copy the proficiency level exactly as written in the CV, after whitespace
  normalisation.
- Leave `reading`, `speaking`, `writing`, `reading_cefr`, `speaking_cefr`,
  `writing_cefr` as "" — CEFR mapping is handled by the renderer, not here.

### key_qualifications
- Extract the key qualifications or profile summary exactly as written in the CV
  if such a section exists. One string per bullet or sentence.
- This is source material only — it is NOT tailored to any specific assignment.
- Leave as [] if no such section exists in the CV.

### Fields to leave empty — always
- `proposed_position`, `category`, `employer`, `years_with_firm`: always "".
  These are injected by the pipeline from human-supplied params, never extracted.
- `generated_fields`: always [].
  Populated later by the Fields Generator agent.
- `world_bank_affiliation`: leave as "" unless explicitly present in the CV.

## Schema
{{ CVData.model_json_schema() }}
"""


def _build_prompt(system: str) -> str:
    schema_json = json.dumps(CVData.model_json_schema(), indent=2)
    return system.replace("{{ CVData.model_json_schema() }}", schema_json)


def run(run_dir: Path, cv_text: str, params: dict) -> CVData:
    """
    Extract CV text into a CVData object, inject pipeline params, and write
    runs/{session_id}/cv_data.json.

    Args:
        run_dir: Path to the session run directory.
        cv_text: Tagged plain text from pipeline/extractor.
        params:  Pipeline params dict (proposed_position, category, employer,
                 years_with_firm, donor, page_limit, ...).

    Returns:
        Validated CVData instance.
    """
    update_step(run_dir, "cv_extractor", "running")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=_build_prompt(SYSTEM_PROMPT),
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract the CV below into a CVData JSON object.\n\n" f"<cv>\n{cv_text}\n</cv>"
                ),
            }
        ],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "cv_extractor", "failed")
        raise ValueError(
            "CV Extractor response was truncated (max_tokens reached). "
            "Increase max_tokens or reduce CV length."
        )

    raw = strip_code_fences(response.content[0].text.strip())

    try:
        parsed = CVData.model_validate_json(raw)
    except Exception as exc:
        update_step(run_dir, "cv_extractor", "failed")
        raise ValueError(
            f"CV Extractor returned invalid JSON: {exc}\n\nRaw output:\n{raw}"
        ) from exc

    # Inject upfront params — agent correctly leaves these empty during extraction
    parsed.proposed_position = params.get("proposed_position", "")
    parsed.category = params.get("category", "")
    parsed.employer = params.get("employer", "")
    parsed.years_with_firm = params.get("years_with_firm", "")

    output = {
        "approved": False,
        "approved_at": None,
        "data": parsed.model_dump(),
    }
    (run_dir / "cv_data.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    update_step(run_dir, "cv_extractor", "done")
    return parsed

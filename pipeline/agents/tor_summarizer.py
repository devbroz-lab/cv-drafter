"""
Agent 2 — ToR Summarizer.

Reads tagged Terms of Reference text and extracts it into a DistilledToR object
using Claude.  Runs in parallel with Agent 1 (CV Extractor) during Phase 1.

Input:  plain text of the ToR document (or "" if no ToR was uploaded)
Output: runs/{session_id}/tor_data.json
"""

from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from models import DistilledToR
from pipeline.manifest import update_step
from pipeline.utils import strip_code_fences

client = Anthropic()

SYSTEM_PROMPT = """
You are the ToR Summarizer agent in a document processing pipeline. Your sole
job is to read a Terms of Reference (ToR) document and extract its contents
into a structured JSON object that strictly conforms to the DistilledToR schema.

## Output rules
- Respond with a single JSON object and nothing else.
- No preamble, no explanation, no markdown fences.
- The JSON must be a valid, complete DistilledToR object.
- Every field defined in the schema must be present.
- All string fields default to "" if not found.
- All list fields default to [] if not found.
- `page_limit_stated` defaults to null if not found.
- Never use null for any field except `page_limit_stated`.

## Extraction rules

### Strictness
- Extract only what is explicitly present in the ToR text.
- Do not infer, assume, or generate content.
- If a field is not stated, leave it as "" or [].

### position_title
- Extract the exact title of the expert role being filled.
- If multiple positions are described in the ToR, extract only the one
  that is most prominently featured or listed first.
- Do not paraphrase — copy the title verbatim, then apply Title Case
  normalisation.

### sector
- Extract the primary sector as a single short noun phrase.
- Examples: "Renewable Energy", "Urban Water Supply", "Public Financial
  Management", "Transport Infrastructure".
- If the ToR spans multiple sectors, pick the dominant one.

### key_tasks
- Extract actual task statements — concrete actions the expert must perform.
- Each item must be a full, standalone sentence or clause.
- Do NOT extract section headings, role titles, or general scope descriptions.
- Good example: "Develop a training curriculum for 50 local grid engineers
  covering SCADA operation and fault diagnosis."
- Bad example: "Scope of Work" / "Technical Assistance" / "Advisory Services"
- If the ToR contains a numbered task list, extract each item as a separate
  string. If tasks are embedded in prose, decompose them into discrete items.

### required_qualifications
- Extract academic degrees, certifications, and professional credentials
  explicitly listed as required or mandatory.
- One string per qualification.

### required_competencies vs preferred_competencies
- `required_competencies`: only items the ToR marks as required, mandatory,
  essential, or must-have.
- `preferred_competencies`: only items the ToR marks as preferred, desirable,
  advantageous, or an asset.
- If the ToR does not distinguish, put all competencies in
  `required_competencies` and leave `preferred_competencies` as [].

### sector_keywords
- Extract domain-specific technical terms, acronyms, and jargon that a
  screener would look for in a CV.
- Do NOT include generic terms like "project management", "communication".

### language_requirements
- Extract only explicit language requirements.
- Format each as: "Language — Level" where level is as stated in the ToR.

### country_experience_required
- Extract only countries or regions explicitly named as required or preferred
  experience locations.

### page_limit_stated
- Search the entire ToR for any clause that restricts the length of submitted CVs.
- If found: set `page_limit_stated` to the integer page number only.
- If not found: set `page_limit_stated` to null.

### page_limit_source
- If `page_limit_stated` is not null, copy the verbatim clause from the ToR
  that states the page limit.
- If `page_limit_stated` is null, leave `page_limit_source` as "".

## Schema
{{ DistilledToR.model_json_schema() }}
"""


def _build_prompt(system: str) -> str:
    schema_json = json.dumps(DistilledToR.model_json_schema(), indent=2)
    return system.replace("{{ DistilledToR.model_json_schema() }}", schema_json)


def run(run_dir: Path, tor_text: str) -> DistilledToR:
    """
    Extract ToR text into a DistilledToR object and write
    runs/{session_id}/tor_data.json.

    If no ToR was provided, tor_text will be "".  The agent will return a
    minimal DistilledToR with all fields at their defaults.

    Args:
        run_dir:  Path to the session run directory.
        tor_text: Full plain text of the ToR document, or "" if none.

    Returns:
        Validated DistilledToR instance.
    """
    update_step(run_dir, "tor_summarizer", "running")

    content = (
        "Extract the ToR below into a DistilledToR JSON object.\n\n" f"<tor>\n{tor_text}\n</tor>"
        if tor_text.strip()
        else (
            "No Terms of Reference document was provided for this session. "
            "Return a minimal DistilledToR JSON object with all fields at their "
            "default empty values (strings as '', lists as [], "
            "page_limit_stated as null)."
        )
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=_build_prompt(SYSTEM_PROMPT),
        messages=[{"role": "user", "content": content}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "tor_summarizer", "failed")
        raise ValueError(
            "ToR Summarizer response was truncated (max_tokens reached). "
            "Increase max_tokens or reduce ToR length."
        )

    raw = strip_code_fences(response.content[0].text.strip())

    try:
        parsed = DistilledToR.model_validate_json(raw)
    except Exception as exc:
        update_step(run_dir, "tor_summarizer", "failed")
        raise ValueError(
            f"ToR Summarizer returned invalid JSON: {exc}\n\nRaw output:\n{raw}"
        ) from exc

    output = {
        "approved": False,
        "approved_at": None,
        "data": parsed.model_dump(),
    }
    (run_dir / "tor_data.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    update_step(run_dir, "tor_summarizer", "done")
    return parsed

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
You are the ToR Summarizer agent in a document processing pipeline. Your job
is to read a Terms of Reference (ToR) document and extract **every distinct
expert role / expert pool** it describes into a JSON array of DistilledToR
objects, each strictly conforming to the schema shown below.

## Output rules
- Respond with a single top-level JSON object: { "pools": [ <DistilledToR>, ... ] }
- No preamble, no explanation, no markdown fences.
- Each element of "pools" must be a valid, complete DistilledToR object.
- Every field defined in the schema must be present in each pool object.
- All string fields default to "" if not found.
- All list fields default to [] if not found.
- `page_limit_stated` defaults to null if not found.
- Never use null for any field except `page_limit_stated`.
- If only one expert role exists in the ToR, "pools" still has exactly one element.

## How to identify expert pools / roles
- Look for numbered or labelled position listings (e.g. "Expert 1", "Expert 2",
  "Team Leader", "National Consultant", "Pool A / Pool B").
- Look for section headings that name distinct roles, tables of required experts,
  or repeated "Scope of Work" blocks with different titles.
- If the same role appears multiple times (e.g. "Senior Engineer ×2"),
  produce **one** pool entry for that role — not two.
- Fields that are shared across all roles (e.g. language requirements, country
  context) should be duplicated into each pool object; do not omit them just
  because they are not role-specific.

## Extraction rules (apply to every pool individually)

### Strictness
- Extract only what is explicitly present in the ToR text for that role.
- Do not infer, assume, or generate content.
- If a field is not stated for a specific role, leave it as "" or [].

### position_title
- Extract the exact title of the expert role being filled.
- Do not paraphrase — copy the title verbatim, then apply Title Case
  normalisation.

### sector
- Extract the primary sector as a single short noun phrase.
- Examples: "Renewable Energy", "Urban Water Supply", "Public Financial
  Management", "Transport Infrastructure".
- If the role spans multiple sectors, pick the dominant one.

### key_tasks
- Extract actual task statements for THIS role — concrete actions the expert
  must perform.
- Each item must be a full, standalone sentence or clause.
- Do NOT extract section headings, role titles, or general scope descriptions.
- Good example: "Develop a training curriculum for 50 local grid engineers
  covering SCADA operation and fault diagnosis."
- Bad example: "Scope of Work" / "Technical Assistance" / "Advisory Services"
- If tasks are in a numbered list, extract each as a separate string. If tasks
  are in prose, decompose them into discrete items.

### required_qualifications
- Extract academic degrees, certifications, and professional credentials
  explicitly listed as required or mandatory for THIS role.
- One string per qualification.

### required_competencies vs preferred_competencies
- `required_competencies`: only items marked as required, mandatory, essential,
  or must-have for this role.
- `preferred_competencies`: only items marked as preferred, desirable,
  advantageous, or an asset.
- If the ToR does not distinguish, put all competencies in
  `required_competencies` and leave `preferred_competencies` as [].

### sector_keywords
- Extract domain-specific technical terms, acronyms, and jargon a screener
  would look for in a CV for THIS role.
- Do NOT include generic terms like "project management", "communication".

### language_requirements
- Extract only explicit language requirements (may be shared across roles).
- Format each as: "Language — Level" as stated in the ToR.

### country_experience_required
- Extract only countries or regions explicitly named as required or preferred
  experience for this role.

### page_limit_stated
- Search the entire ToR for any clause restricting CV length.
- If found: integer page number only.
- If not found: null.

### page_limit_source
- If `page_limit_stated` is not null, copy the verbatim clause from the ToR.
- If null, leave as "".

## Schema (applies to every element in "pools")
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
        "Extract the ToR below into a DistilledToR pools JSON object.\n\n"
        f"<tor>\n{tor_text}\n</tor>"
        if tor_text.strip()
        else (
            "No Terms of Reference document was provided for this session. "
            "Return a JSON object with a single minimal DistilledToR in `pools`, "
            "with all fields at their default empty values (strings as '', lists as [], "
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
        parsed = json.loads(raw)
        pools_raw = parsed.get("pools")
        if not isinstance(pools_raw, list) or len(pools_raw) == 0:
            raise ValueError("`pools` must be a non-empty list")
        pools = [DistilledToR.model_validate(pool) for pool in pools_raw]
    except Exception as exc:
        update_step(run_dir, "tor_summarizer", "failed")
        raise ValueError(
            f"ToR Summarizer returned invalid JSON: {exc}\n\nRaw output:\n{raw}"
        ) from exc

    output = {
        "approved": False,
        "approved_at": None,
        "pools": [pool.model_dump() for pool in pools],
        "selected_pool_index": 0,
    }
    (run_dir / "tor_data.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    update_step(run_dir, "tor_summarizer", "done")
    return pools[0]

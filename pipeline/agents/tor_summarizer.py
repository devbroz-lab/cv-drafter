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
from pipeline.config import ANTHROPIC_MODEL
from pipeline.manifest import update_step
from pipeline.utils import extract_json_object, strip_code_fences

client = Anthropic()

SYSTEM_PROMPT_A2 = """
You are the ToR Summarizer agent in a document processing pipeline. Your job
is to read a Terms of Reference (ToR) document and extract **every distinct
expert role / expert pool** it describes into a JSON array of DistilledToR
objects, each strictly conforming to the schema shown below.

## Output contract (READ FIRST)
- Your entire response must be a single JSON object — nothing else.
- The FIRST non-whitespace character MUST be `{`. The LAST MUST be `}`.
- No preamble. No reasoning text. No "Here is the JSON". No explanation.
- No markdown fences (no ```json, no ```).
- Do all reasoning silently. Only the JSON object is emitted.
- Respond with a single top-level JSON object: { "pools": [ <DistilledToR>, ... ] }
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

### scoring_keywords

Populate the `scoring_keywords` block with keyword sets that will be used by
the Python relevance scorer to evaluate how well each CV project matches this
role. Three lists are required:

**`explicit`** — directly stated requirements. Extract verbatim from the ToR:
- Geographic requirements (countries, regions).
- Minimum years of experience stated numerically.
- Named sectors, programmes, or donor-specific terminology.
- Examples: `["South Africa", "7 years experience", "electricity sector",
  "REIPPPP"]`

**`scope_implied`** — thematic areas described in the project scope or
background section. Identify the technical domains the project operates in,
even if not listed as explicit requirements:
- Technology types, methodologies, systems, standards.
- Examples: `["grid integration", "renewable energy", "distribution network",
  "prosumers", "energy storage", "voltage regulation"]`

**`role_implied`** — technical terms a competent expert holding this position
title would routinely work with, even if the ToR does not spell them out. This
is a light **inferential** step: reason from the position title and pool name
to the technical vocabulary of the field.
- A "Grid Code Expert" implies: `["grid code", "stability criteria",
  "transmission planning", "balancing mechanism", "ancillary services"]`
- A "Regulatory Economist" implies: `["tariff design", "cost of service study",
  "regulatory accounting", "rate of return", "revenue requirement"]`
- Examples must be specific technical terms — never generic terms like
  "project management" or "stakeholder engagement".

**Quantity guidelines**:
- Each list should contain 5–15 keywords.
- Prefer multi-word technical terms over single generic words.
- Use lowercase unless the term is an acronym or proper noun.
- If the source text provides no signal for a list, leave it as `[]`.

**Non-empty guarantee**: For any non-empty ToR input, at least one of the
three keyword lists must be populated. Even on long PDF inputs:
- `role_implied`: infer at least 3–5 keywords from the `position_title`
  alone. You always have the position title even before reading the full ToR.
  Running on Sonnet, you have the reasoning capacity to produce role-implied
  keywords from the title alone — do not return an empty `role_implied` list
  unless `position_title` is itself empty.
- `explicit`: extract at minimum any geography and experience threshold
  requirements named in the ToR.

Returning all three lists empty for a non-empty ToR is treated as an A2
extraction failure by downstream validation.

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

### geography
- Populate as a single short string summarising the primary geographic scope
  of the assignment (e.g. "South Africa", "Sub-Saharan Africa", "West Africa",
  "Global", "Nigeria — Lagos State").
- Derive from the same source material that informs `country_experience_required`.
- Use the most specific geographic label that is accurate — prefer a country
  name over a continent name where the ToR identifies a specific country.
- If multiple countries of roughly equal weight are named, write the region
  instead (e.g. "East Africa").
- If the geographic scope is genuinely ambiguous or not stated, leave as "".
- This is a human-readable display field only. The structured list
  `country_experience_required` is the canonical machine-readable equivalent.

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
        model=ANTHROPIC_MODEL,
        max_tokens=16000,
        system=_build_prompt(SYSTEM_PROMPT_A2),
        messages=[{"role": "user", "content": content}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "tor_summarizer", "failed")
        raise ValueError(
            "ToR Summarizer response was truncated (max_tokens reached). "
            "Increase max_tokens or reduce ToR length."
        )

    raw = strip_code_fences(response.content[0].text.strip())
    raw = extract_json_object(raw)

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

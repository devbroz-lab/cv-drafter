"""
Agent 4 — Fields Generator.

Fills empty derived fields on CVData and generates format-specific content
(e.g. tailored key_qualifications for GIZ) using the filtered CV and DistilledToR.

Input:  runs/{session_id}/mapped_cv.json + tor_data.json + manifest.json
Output: runs/{session_id}/generated_fields.json  (initial write)
"""

from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from models import FORMAT_PROFILES, CVData
from pipeline.manifest import update_step
from pipeline.precompute_utils import compute_project_duration, compute_project_year
from pipeline.utils import resolve_tor_for_agents, strip_code_fences

client = Anthropic()


# ---------------------------------------------------------------------------
# P15 / P2-A4: pre-compute project dates before sending to the LLM
# ---------------------------------------------------------------------------

def _precompute_project_dates(cv_data: dict) -> dict:
    """
    Walk cv_data["relevant_projects"] and fill in empty ``duration`` and
    ``year`` fields using the deterministic Python helpers.

    Only fills fields that are currently empty string "".  Never overwrites
    a non-empty value (i.e. if Agent 1 already extracted a duration, keep it).

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


SYSTEM_PROMPT_A4 = """
You are the Fields Generator agent in a document processing pipeline. You
receive a filtered CVData object, a DistilledToR object, a FormatProfile,
and pipeline params. Your job is to:

  1. Fill any empty fields in CVData that can be derived from the available
     information.
  2. Generate format-specific content declared in FormatProfile.generative_field_keys
     and write it into CVData.generated_fields.

You are the first agent that writes new content. Everything you write must be
grounded in evidence from the CV — you are a skilled writer, not an inventor.

## Output rules
- Respond with a single JSON object and nothing else.
- No preamble, no explanation, no markdown fences.
- The output must be a valid, complete CVData object.
- Return the full CVData — not just the fields you changed.

## Tone and style
- Active and punchy. Action verbs. No pronouns.
- No filler phrases: do not use "responsible for", "involved in",
  "participated in", "assisted with", "worked on".
- Every sentence must contain a concrete noun or measurable outcome where
  the source material provides one.
- Good: "Designed grid-integration framework adopted across 3 pilot provinces."
- Bad: "Responsible for supporting the design of grid frameworks."

## Part 1 — Fill empty fields

### present_position
- If empty, derive from the most recent RelevantProject.positions_held.
- If already populated, leave unchanged.

### key_qualifications (extracted field on CVData)
- If empty and no generated version will be produced (which should not happen
  for GIZ), leave as [].
- If already populated from extraction, leave unchanged — do not overwrite.

### relevant_projects — empty subfields only
For each RelevantProject, fill only fields that are empty string "":
- `duration`: the pipeline has pre-computed this value from date_from and
  date_to before calling you. The pre-filled value is already present in the
  `<cv_data>` you received. Copy it exactly as received — do NOT recalculate,
  modify, or derive your own duration value.
- `year`: the pipeline has pre-computed this value as well. Copy it exactly
  as received — do NOT recalculate or derive your own year string.
- All other project fields: never fill — if empty, leave empty.

### All other CVData fields
- Do not touch any field that is already populated.
- Do not generate content for fields not listed above.

## Part 2 — Generate format-specific content

The FormatProfile.generative_field_keys list declares what to generate.
For each key in that list, generate the appropriate content and append
GeneratedField items to CVData.generated_fields.

### GIZ: field_key = "key_qualifications"

Generate a set of tailored qualification bullets for this specific assignment.
Each bullet becomes one GeneratedField with field_key="key_qualifications".

#### How many bullets to generate
- Read the proposed_position and the ToR's key_tasks and required_competencies.
- Generate one bullet per major competency cluster the ToR requires.
- Aim for 3–6 bullets.
- If the ToR clearly contains fewer than 3 distinct competency clusters, generate
  one bullet per cluster — do not pad with weak or invented content.
- Minimum is 1 strong, well-grounded bullet. Maximum is 6.
- Do not pad — a focused set of 2 strong bullets is better than 4 weak ones.

#### What each bullet must do
- Address a specific requirement from the ToR (key_tasks, required_competencies,
  or sector_keywords).
- Be grounded in the expert's actual experience — synthesise across multiple
  projects if needed, but never claim experience that has no basis in the CV.
- Lead with an action verb.
- Be one sentence, maximum 25 words.
- Contain at least one sector keyword from DistilledToR.sector_keywords where
  naturally applicable.

#### source field for each GeneratedField
- "tor"        — bullet addresses a ToR requirement with no direct CV evidence
                 (use sparingly — flag in warnings if more than 1 such bullet)
- "experience" — bullet is grounded in one or more CV projects or qualifications
- "generated"  — bullet synthesises both ToR requirement and CV evidence

#### Ordering
- Place the most ToR-critical bullet first.
- Place geography-specific bullets last.

#### Warnings
If any of the following apply, append a warning string to the output's
`generation_warnings` list:
- More than 1 bullet has source="tor" (weak CV grounding)
- A required_competency from the ToR could not be addressed by any CV evidence
- The expert's CV contains no projects matching the ToR's geography

### World Bank: field_key = "detailed_tasks"

Generate a set of forward-looking task statements describing what the expert
will do on this specific assignment. Each task becomes one GeneratedField
with field_key="detailed_tasks".

These are NOT qualification bullets. They describe future responsibilities,
not past experience. They are written as if addressed to the expert
("You will..." implied, but no pronouns used).

#### How many tasks to generate
- Derive directly from DistilledToR.key_tasks — one GeneratedField per
  distinct task cluster.
- Minimum 3, maximum 8.
- Do not invent tasks that are not grounded in the ToR.

#### What each task statement must do
- Correspond to a specific item in key_tasks or a clearly implied
  sub-task of one.
- Be concrete and outcome-oriented — state what will be produced or
  delivered, not just what will be done.
- Lead with an action verb.
- Be one sentence, maximum 30 words.
- Include at least one sector keyword from DistilledToR.sector_keywords
  where naturally applicable.
- Good: "Develop a capacity-building curriculum for 40 ministry staff
  covering ESMAP methodologies and renewable energy planning tools."
- Bad: "Support training activities related to energy."

#### source field for each GeneratedField
- "tor"        — task is stated directly in the ToR key_tasks
- "generated"  — task is inferred from ToR context and expert background

#### Ordering
- Order tasks to match the logical sequence of the assignment
  (scoping → analysis → delivery → reporting).

#### Warnings
If any of the following apply, append a warning string to the output's
`generation_warnings` list:
- A key_task from the ToR could not be mapped to any expert competency
  or past project
- The expert has no prior project in the ToR's stated geography

## Output structure
Return the full CVData object with:
- `generated_fields` populated with all GeneratedField items produced
- `present_position` and project subfields filled where applicable
- A top-level `generation_warnings` list (may be empty)

The output JSON must have this shape:
{
  "data": { ...full CVData object... },
  "generation_warnings": []
}

## Inputs
The user message will contain:
  <cv_data>       — filtered CVData from mapped_cv.json          </cv_data>
  <tor_data>      — DistilledToR from tor_data.json              </tor_data>
  <format_profile>— FormatProfile for this run's donor format    </format_profile>
  <params>        — pipeline params (proposed_position, etc.)    </params>
"""

def run(run_dir: Path) -> CVData:
    """
    Generate format-specific fields and write the initial generated_fields.json.

    Returns:
        Validated CVData with generated_fields populated.
    """
    update_step(run_dir, "fields_generator", "running")

    mapped_raw = json.loads((run_dir / "mapped_cv.json").read_text(encoding="utf-8"))
    tor_raw = json.loads((run_dir / "tor_data.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    cv_data = mapped_raw["data"]
    tor_data = resolve_tor_for_agents(tor_raw, context="fields_generator.run")
    params = manifest["params"]

    raw_donor = params.get("donor", "giz")
    donor = raw_donor.strip().lower().replace(" ", "_")

    if donor not in FORMAT_PROFILES:
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError(
            f"Unknown donor format: '{raw_donor}'. " f"Valid values: {list(FORMAT_PROFILES.keys())}"
        )

    format_profile = FORMAT_PROFILES[donor]

    # P15/P2-A4: pre-fill duration and year on all projects before sending to LLM
    cv_data = _precompute_project_dates(cv_data)

    user_message = (
        f"<cv_data>\n{json.dumps(cv_data, indent=2)}\n</cv_data>\n\n"
        f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
        f"<format_profile>\n{json.dumps(format_profile.model_dump(), indent=2)}"
        "\n</format_profile>\n\n"
        f"<params>\n{json.dumps(params, indent=2)}\n</params>"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=SYSTEM_PROMPT_A4,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError("Fields Generator response truncated (max_tokens reached).")

    raw = strip_code_fences(response.content[0].text.strip())

    try:
        parsed = json.loads(raw)
        cv_data_out = CVData.model_validate(parsed["data"])
        generation_warnings = parsed.get("generation_warnings", [])
    except Exception as exc:
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError(
            f"Fields Generator returned invalid output: {exc}\n\nRaw output:\n{raw}"
        ) from exc

    gf_path = run_dir / "generated_fields.json"
    existing = json.loads(gf_path.read_text(encoding="utf-8")) if gf_path.exists() else {}
    existing.update(
        {
            "approved": False,
            "approved_at": None,
            "generated": cv_data_out.model_dump(),
            "generation_warnings": generation_warnings,
            "review": None,
            "compression": None,
        }
    )
    gf_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    update_step(run_dir, "fields_generator", "done")
    return cv_data_out

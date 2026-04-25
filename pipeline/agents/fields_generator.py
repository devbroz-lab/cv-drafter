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
from pipeline.utils import strip_code_fences

client = Anthropic()

SYSTEM_PROMPT = """
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

### relevant_projects — empty subfields only
For each RelevantProject, fill only fields that are empty string "":
- `duration`: calculate from date_from and date_to if both are present.
  Format as "N months" or "N years" rounded to nearest whole unit.
  If either date is missing or "Present", leave as "".
- `year`: derive as "YYYY" or "YYYY-YYYY" from date_from and date_to.
  Leave as "" if dates are missing.
- All other project fields: never fill — if empty, leave empty.

### All other CVData fields
- Do not touch any field that is already populated.
- Do not generate content for fields not listed above.

## Part 2 — Generate format-specific content

The FormatProfile.generative_field_keys list declares what to generate.
For each key in that list, generate the appropriate content and append
GeneratedField items to CVData.generated_fields.

### GIZ: field_key = "key_qualifications"

Generate tailored qualification bullets for this specific assignment.
Each bullet becomes one GeneratedField with field_key="key_qualifications".

#### How many bullets
- Minimum 3 bullets, maximum 6 bullets.
- One bullet per major competency cluster the ToR requires.

#### What each bullet must do
- Address a specific requirement from the ToR.
- Be grounded in the expert's actual experience.
- Lead with an action verb.
- Be one sentence, maximum 25 words.
- Contain at least one sector keyword from DistilledToR.sector_keywords where applicable.

#### source field for each GeneratedField
- "tor"        — bullet addresses a ToR requirement with no direct CV evidence (use sparingly)
- "experience" — bullet is grounded in one or more CV projects or qualifications
- "generated"  — bullet synthesises both ToR requirement and CV evidence

#### Ordering
- Place the most ToR-critical bullet first.
- Place geography-specific bullets last.

#### Warnings
If any of the following apply, append a warning string to generation_warnings:
- More than 1 bullet has source="tor"
- A required_competency from the ToR could not be addressed by any CV evidence
- The expert's CV contains no projects matching the ToR's geography

## Output structure
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
    tor_data = tor_raw["data"]
    params = manifest["params"]

    raw_donor = params.get("donor", "giz")
    donor = raw_donor.strip().lower().replace(" ", "_")

    if donor not in FORMAT_PROFILES:
        update_step(run_dir, "fields_generator", "failed")
        raise ValueError(
            f"Unknown donor format: '{raw_donor}'. " f"Valid values: {list(FORMAT_PROFILES.keys())}"
        )

    format_profile = FORMAT_PROFILES[donor]

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
        system=SYSTEM_PROMPT,
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
